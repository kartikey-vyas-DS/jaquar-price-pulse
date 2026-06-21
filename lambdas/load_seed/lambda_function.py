import csv
import io
import os
import ssl
from typing import Iterable

import boto3
import pg8000.dbapi


SCHEMA_SQL = """
create schema if not exists raw;
create schema if not exists staging;
create schema if not exists mart;

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
);

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
);

create index if not exists idx_price_snapshots_watch_date
on raw.price_snapshots (watch_id, snapshot_date);

create index if not exists idx_price_snapshots_product_code
on raw.price_snapshots (product_code);
"""


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def read_csv_from_s3(s3, bucket: str, key: str) -> list[dict]:
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(body)))


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


def execute_statements(cur, sql: str) -> None:
    for statement in [part.strip() for part in sql.split(";") if part.strip()]:
        cur.execute(statement)


def load_watchlist(cur, rows: Iterable[dict]) -> int:
    rows = list(rows)
    cur.execute("truncate table raw.price_snapshots;")
    cur.execute("truncate table raw.watchlist cascade;")

    for row in rows:
        cur.execute(
            """
            insert into raw.watchlist (
                watch_id, product_code, series, product_name, color, product_url,
                category, current_mrp, alert_threshold_pct, is_active, priority, notes
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row["watch_id"],
                row["product_code"],
                row["series"],
                row["product_name"],
                row["color"],
                row["product_url"],
                row["category"],
                row["current_mrp"],
                row["alert_threshold_pct"],
                as_bool(row["is_active"]),
                int(row["priority"]),
                row["notes"],
            ),
        )
    return len(rows)


def load_history(cur, rows: Iterable[dict]) -> int:
    rows = list(rows)
    for row in rows:
        cur.execute(
            """
            insert into raw.price_snapshots (
                snapshot_date, scrape_run_id, watch_id, product_code, series,
                product_name, color, mrp, source_url, is_synthetic
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (snapshot_date, watch_id) do update set
                scrape_run_id = excluded.scrape_run_id,
                product_code = excluded.product_code,
                series = excluded.series,
                product_name = excluded.product_name,
                color = excluded.color,
                mrp = excluded.mrp,
                source_url = excluded.source_url,
                is_synthetic = excluded.is_synthetic,
                ingested_at = now()
            """,
            (
                row["snapshot_date"],
                row["scrape_run_id"],
                row["watch_id"],
                row["product_code"],
                row["series"],
                row["product_name"],
                row["color"],
                row["mrp"],
                row["source_url"],
                as_bool(row["is_synthetic"]),
            ),
        )
    return len(rows)


def lambda_handler(event, context):
    bucket = env("S3_BUCKET")
    watchlist_key = env("WATCHLIST_KEY", "watchlist/jaquar_price_watchlist_50.csv")
    history_key = env("HISTORY_KEY", "seed/jaquar_price_history_seed_synthetic.csv")

    s3 = boto3.client("s3")
    watchlist_rows = read_csv_from_s3(s3, bucket, watchlist_key)
    history_rows = read_csv_from_s3(s3, bucket, history_key)

    conn = connect()
    try:
        cur = conn.cursor()
        execute_statements(cur, SCHEMA_SQL)
        watchlist_count = load_watchlist(cur, watchlist_rows)
        history_count = load_history(cur, history_rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "ok",
        "bucket": bucket,
        "watchlist_key": watchlist_key,
        "history_key": history_key,
        "watchlist_rows": watchlist_count,
        "history_rows": history_count,
    }
