import csv
import io
import json
import os
import random
import re
import ssl
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable
from urllib.parse import parse_qs, urlparse

import boto3
import pg8000.dbapi
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.jaquar.com"
API_ENDPOINT = "https://www.jaquar.com/en/shoppingcart/productdetails_attributechange"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": BASE_URL,
}
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
BACKOFF_BASE = float(os.environ.get("BACKOFF_BASE", "4"))
TIMEOUT_SECS = int(os.environ.get("TIMEOUT_SECS", "25"))
DELAY_PRODUCTS = float(os.environ.get("DELAY_PRODUCTS", "1.0"))
DELAY_VARIANTS = float(os.environ.get("DELAY_VARIANTS", "0.4"))


@dataclass
class WatchRow:
    watch_id: str
    product_code: str
    series: str
    product_name: str
    color: str
    product_url: str
    category: str
    current_mrp: str
    alert_threshold_pct: str
    is_active: bool
    priority: int
    notes: str


@dataclass
class VariantRow:
    product_code: str
    product_name: str
    color: str
    mrp: str
    source_url: str


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def clean_price(raw: str) -> str:
    if not raw:
        return ""
    return re.sub(r"[^\d.]", "", raw.replace(",", ""))


def decimal_or_none(value: str | None) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    return Decimal(str(value).strip())


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(BASE_URL + "/en/", timeout=15)
    except Exception:
        pass
    return session


def get_with_retry(session: requests.Session, url: str) -> requests.Response:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=TIMEOUT_SECS)
            if response.status_code == 429:
                wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 2)
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.HTTPError):
            if attempt == MAX_RETRIES:
                raise
            wait = BACKOFF_BASE * attempt + random.uniform(0, 2)
            time.sleep(wait)
    raise RuntimeError(f"GET retries exhausted for {url}")


def post_with_retry(session: requests.Session, url: str, **kwargs) -> requests.Response:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.post(url, timeout=TIMEOUT_SECS, **kwargs)
            if response.status_code == 429:
                wait = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 2)
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.HTTPError):
            if attempt == MAX_RETRIES:
                raise
            wait = BACKOFF_BASE * attempt + random.uniform(0, 2)
            time.sleep(wait)
    raise RuntimeError(f"POST retries exhausted for {url}")


def get_soup(session: requests.Session, url: str) -> BeautifulSoup:
    response = get_with_retry(session, url)
    return BeautifulSoup(response.text, "lxml")


def product_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return (query.get("Id") or query.get("id") or [""])[0]


def extract_page_product_id(soup: BeautifulSoup, fallback: str) -> str:
    sku_div = soup.select_one("div.descrpt-value[id^='sku-']")
    if sku_div:
        return sku_div["id"].split("-")[-1]

    qty_input = soup.select_one("input[name*='EnteredQuantity']")
    if qty_input:
        match = re.search(r"addtocart_(\d+)\.", qty_input.get("name", ""))
        if match:
            return match.group(1)

    form = soup.select_one("form#product-details-form, form[action*='addtocart']")
    if form:
        match = re.search(r"/(\d+)", form.get("action", ""))
        if match:
            return match.group(1)

    return fallback


def fetch_variant_api(
    session: requests.Session,
    product_id: str,
    attribute_id: str,
    attr_value_id: str,
    csrf_token: str,
) -> dict | None:
    params = {
        "productId": product_id,
        "validateAttributeConditions": "False",
        "loadPicture": "True",
    }
    form_data = {
        f"product_attribute_{attribute_id}": attr_value_id,
        f"addtocart_{product_id}.EnteredQuantity": "1",
        "__RequestVerificationToken": csrf_token,
    }
    response = post_with_retry(session, API_ENDPOINT, params=params, data=form_data)
    return response.json()


def scrape_product_variants(session: requests.Session, product_url: str) -> list[VariantRow]:
    soup = get_soup(session, product_url)
    token_input = soup.select_one('input[name="__RequestVerificationToken"]')
    csrf_token = token_input["value"] if token_input else ""
    page_product_id = extract_page_product_id(soup, product_id_from_url(product_url))

    swatch_ul = soup.select_one("ul.attribute-squares.image-squares")
    swatches = []
    if swatch_ul:
        attribute_id = swatch_ul.get("id", "").replace("image-squares-", "")
        for li in swatch_ul.select("li[data-attr-value]"):
            radio = li.select_one("input[type='radio']")
            swatches.append(
                {
                    "attribute_id": attribute_id,
                    "attr_value_id": li["data-attr-value"],
                    "title": radio["title"] if radio else "",
                }
            )

    if not swatches:
        name_h1 = soup.select_one("h1[id^='product-name-']")
        sku_el = soup.select_one("div.descrpt-value[id^='sku-']")
        price_el = soup.select_one("span.price.actual-price, span.actual-price")
        color_span = soup.select_one("span.value")
        return [
            VariantRow(
                product_code=sku_el.get_text(strip=True) if sku_el else "",
                product_name=name_h1.get_text(strip=True) if name_h1 else "",
                color=color_span.get_text(strip=True) if color_span else "",
                mrp=clean_price(price_el.get_text(strip=True)) if price_el else "",
                source_url=product_url,
            )
        ]

    variants = []
    for swatch in swatches:
        time.sleep(DELAY_VARIANTS)
        data = fetch_variant_api(
            session=session,
            product_id=page_product_id,
            attribute_id=swatch["attribute_id"],
            attr_value_id=swatch["attr_value_id"],
            csrf_token=csrf_token,
        )
        if not data:
            continue
        variants.append(
            VariantRow(
                product_code=data.get("sku", ""),
                product_name=data.get("productName", ""),
                color=swatch["title"],
                mrp=clean_price(data.get("price", "")),
                source_url=product_url,
            )
        )
    return variants


def read_watchlist_from_s3(s3, bucket: str, key: str) -> list[WatchRow]:
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read().decode("utf-8-sig")
    rows = []
    for row in csv.DictReader(io.StringIO(body)):
        if not as_bool(row.get("is_active", "true")):
            continue
        rows.append(
            WatchRow(
                watch_id=row["watch_id"],
                product_code=row["product_code"],
                series=row["series"],
                product_name=row["product_name"],
                color=row.get("color", ""),
                product_url=row["product_url"],
                category=row["category"],
                current_mrp=row.get("current_mrp", ""),
                alert_threshold_pct=row.get("alert_threshold_pct", "3.0"),
                is_active=True,
                priority=int(row.get("priority") or 3),
                notes=row.get("notes", ""),
            )
        )
    return rows


def connect():
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return pg8000.dbapi.connect(
        host=env("PGHOST"),
        port=int(env("PGPORT", "5432")),
        database=env("PGDATABASE"),
        user=env("PGUSER"),
        password=env("PGPASSWORD"),
        ssl_context=ssl_context,
        timeout=20,
    )


def ensure_schema(cur) -> None:
    cur.execute("create schema if not exists raw")
    cur.execute(
        """
        create table if not exists raw.watchlist (
            watch_id text primary key,
            product_code text not null,
            series text not null,
            product_name text not null,
            color text,
            product_url text not null,
            category text not null,
            current_mrp numeric(12, 2),
            alert_threshold_pct numeric(8, 2) not null default 3.0,
            is_active boolean not null default true,
            priority integer not null default 3,
            notes text,
            loaded_at timestamptz not null default now()
        )
        """
    )
    cur.execute(
        """
        create table if not exists raw.price_snapshots (
            snapshot_date date not null,
            scrape_run_id text not null,
            watch_id text not null references raw.watchlist(watch_id),
            product_code text not null,
            series text not null,
            product_name text not null,
            color text,
            mrp numeric(12, 2) not null,
            source_url text not null,
            is_synthetic boolean not null default false,
            ingested_at timestamptz not null default now(),
            primary key (snapshot_date, watch_id)
        )
        """
    )


def upsert_watchlist(cur, rows: Iterable[WatchRow]) -> None:
    for row in rows:
        cur.execute(
            """
            insert into raw.watchlist (
                watch_id, product_code, series, product_name, color, product_url,
                category, current_mrp, alert_threshold_pct, is_active, priority, notes
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s, %s)
            on conflict (watch_id) do update set
                product_code = excluded.product_code,
                series = excluded.series,
                product_name = excluded.product_name,
                color = excluded.color,
                product_url = excluded.product_url,
                category = excluded.category,
                current_mrp = excluded.current_mrp,
                alert_threshold_pct = excluded.alert_threshold_pct,
                is_active = true,
                priority = excluded.priority,
                notes = excluded.notes,
                loaded_at = now()
            """,
            (
                row.watch_id,
                row.product_code,
                row.series,
                row.product_name,
                row.color,
                row.product_url,
                row.category,
                decimal_or_none(row.current_mrp),
                decimal_or_none(row.alert_threshold_pct) or Decimal("3.0"),
                row.priority,
                row.notes,
            ),
        )


def upsert_snapshot(cur, snapshot_date: str, run_id: str, watch: WatchRow, variant: VariantRow) -> None:
    cur.execute(
        """
        insert into raw.price_snapshots (
            snapshot_date, scrape_run_id, watch_id, product_code, series,
            product_name, color, mrp, source_url, is_synthetic
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, false)
        on conflict (snapshot_date, watch_id) do update set
            scrape_run_id = excluded.scrape_run_id,
            product_code = excluded.product_code,
            series = excluded.series,
            product_name = excluded.product_name,
            color = excluded.color,
            mrp = excluded.mrp,
            source_url = excluded.source_url,
            is_synthetic = false,
            ingested_at = now()
        """,
        (
            snapshot_date,
            run_id,
            watch.watch_id,
            variant.product_code or watch.product_code,
            watch.series,
            variant.product_name or watch.product_name,
            variant.color or watch.color,
            decimal_or_none(variant.mrp),
            variant.source_url or watch.product_url,
        ),
    )


def write_raw_snapshot_to_s3(s3, bucket: str, key: str, rows: list[dict]) -> None:
    buffer = io.StringIO()
    fieldnames = [
        "snapshot_date",
        "scrape_run_id",
        "watch_id",
        "product_code",
        "series",
        "product_name",
        "color",
        "mrp",
        "source_url",
        "is_synthetic",
        "scrape_status",
        "error_message",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue().encode("utf-8"), ContentType="text/csv")


def lambda_handler(event, context):
    bucket = env("S3_BUCKET")
    watchlist_key = env("WATCHLIST_KEY", "watchlist/jaquar_price_watchlist_50.csv")
    scrape_limit = int(os.environ.get("SCRAPE_LIMIT", "50"))
    snapshot_date = os.environ.get("SNAPSHOT_DATE", date.today().isoformat())
    run_id = event.get("run_id") if isinstance(event, dict) else None
    run_id = run_id or f"jaquar-live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    s3 = boto3.client("s3")
    watchlist = read_watchlist_from_s3(s3, bucket, watchlist_key)[:scrape_limit]
    grouped: dict[str, list[WatchRow]] = {}
    for row in watchlist:
        grouped.setdefault(row.product_url, []).append(row)

    session = make_session()
    raw_rows = []
    matched = 0
    failed = 0

    conn = connect()
    try:
        cur = conn.cursor()
        ensure_schema(cur)
        upsert_watchlist(cur, watchlist)

        for product_url, watches in grouped.items():
            time.sleep(DELAY_PRODUCTS)
            try:
                variants = scrape_product_variants(session, product_url)
                variants_by_code = {v.product_code.strip().upper(): v for v in variants if v.product_code}
                for watch in watches:
                    variant = variants_by_code.get(watch.product_code.strip().upper())
                    if not variant or not variant.mrp:
                        failed += 1
                        raw_rows.append(
                            {
                                "snapshot_date": snapshot_date,
                                "scrape_run_id": run_id,
                                "watch_id": watch.watch_id,
                                "product_code": watch.product_code,
                                "series": watch.series,
                                "product_name": watch.product_name,
                                "color": watch.color,
                                "mrp": "",
                                "source_url": watch.product_url,
                                "is_synthetic": "false",
                                "scrape_status": "not_matched",
                                "error_message": "product_code not returned by Jaquar variant API",
                            }
                        )
                        continue

                    upsert_snapshot(cur, snapshot_date, run_id, watch, variant)
                    matched += 1
                    raw_rows.append(
                        {
                            "snapshot_date": snapshot_date,
                            "scrape_run_id": run_id,
                            "watch_id": watch.watch_id,
                            "product_code": variant.product_code,
                            "series": watch.series,
                            "product_name": variant.product_name or watch.product_name,
                            "color": variant.color or watch.color,
                            "mrp": variant.mrp,
                            "source_url": variant.source_url,
                            "is_synthetic": "false",
                            "scrape_status": "ok",
                            "error_message": "",
                        }
                    )
            except Exception as exc:
                failed += len(watches)
                for watch in watches:
                    raw_rows.append(
                        {
                            "snapshot_date": snapshot_date,
                            "scrape_run_id": run_id,
                            "watch_id": watch.watch_id,
                            "product_code": watch.product_code,
                            "series": watch.series,
                            "product_name": watch.product_name,
                            "color": watch.color,
                            "mrp": "",
                            "source_url": watch.product_url,
                            "is_synthetic": "false",
                            "scrape_status": "failed",
                            "error_message": str(exc)[:500],
                        }
                    )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    raw_key = f"raw/jaquar/snapshot_date={snapshot_date}/{run_id}.csv"
    write_raw_snapshot_to_s3(s3, bucket, raw_key, raw_rows)

    failure_rate = (failed / len(watchlist)) if watchlist else 0
    max_failure_rate = float(os.environ.get("MAX_FAILURE_RATE", "0.50"))
    if watchlist and failure_rate > max_failure_rate:
        raise RuntimeError(
            f"Jaquar scrape failure rate {failure_rate:.0%} exceeded {max_failure_rate:.0%}; "
            f"matched={matched}, failed={failed}, raw_key={raw_key}"
        )

    return {
        "status": "ok",
        "snapshot_date": snapshot_date,
        "scrape_run_id": run_id,
        "watchlist_rows": len(watchlist),
        "product_pages_scraped": len(grouped),
        "matched_rows": matched,
        "failed_rows": failed,
        "raw_key": raw_key,
    }
