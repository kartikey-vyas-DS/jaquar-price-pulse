import csv
import io
import os
import ssl
from decimal import Decimal
from typing import Iterable

import boto3
import pg8000.dbapi


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def decimal_or_none(value: str | None) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    return Decimal(str(value).strip())


def event_value(event: dict, key: str) -> str | None:
    if key in event:
        return event[key]
    payload = event.get("Payload") if isinstance(event, dict) else None
    if isinstance(payload, dict):
        return payload.get(key)
    return None


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


def read_csv_from_s3(s3, bucket: str, key: str) -> list[dict]:
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(body)))


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


def upsert_watchlist(cur, rows: Iterable[dict]) -> int:
    count = 0
    for row in rows:
        if not as_bool(row.get("is_active", "true")):
            continue
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
                row["watch_id"],
                row["product_code"],
                row["series"],
                row["product_name"],
                row.get("color", ""),
                row["product_url"],
                row["category"],
                decimal_or_none(row.get("current_mrp")),
                decimal_or_none(row.get("alert_threshold_pct")) or Decimal("3.0"),
                int(row.get("priority") or 3),
                row.get("notes", ""),
            ),
        )
        count += 1
    return count


def load_snapshot_rows(cur, rows: Iterable[dict]) -> tuple[int, int]:
    loaded = 0
    skipped = 0
    for row in rows:
        if row.get("scrape_status") != "ok" or not row.get("mrp"):
            skipped += 1
            continue
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
                row["snapshot_date"],
                row["scrape_run_id"],
                row["watch_id"],
                row["product_code"],
                row["series"],
                row["product_name"],
                row.get("color", ""),
                decimal_or_none(row["mrp"]),
                row["source_url"],
            ),
        )
        loaded += 1
    return loaded, skipped


def lambda_handler(event, context):
    event = event or {}
    bucket = env("S3_BUCKET")
    watchlist_key = env("WATCHLIST_KEY", "watchlist/jaquar_price_watchlist_50.csv")
    raw_key = event_value(event, "raw_key")
    if not raw_key:
        raise RuntimeError("Missing raw_key from scraper Lambda output")

    s3 = boto3.client("s3")
    watchlist_rows = read_csv_from_s3(s3, bucket, watchlist_key)
    snapshot_rows = read_csv_from_s3(s3, bucket, raw_key)

    conn = connect()
    try:
        cur = conn.cursor()
        ensure_schema(cur)
        watchlist_count = upsert_watchlist(cur, watchlist_rows)
        loaded_rows, skipped_rows = load_snapshot_rows(cur, snapshot_rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "ok",
        "bucket": bucket,
        "raw_key": raw_key,
        "watchlist_rows": watchlist_count,
        "loaded_snapshot_rows": loaded_rows,
        "skipped_snapshot_rows": skipped_rows,
    }
