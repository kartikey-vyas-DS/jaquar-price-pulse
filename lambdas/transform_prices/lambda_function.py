import os
import ssl

import pg8000.dbapi


TRANSFORM_SQL = """
create schema if not exists staging;
create schema if not exists mart;

create or replace view staging.stg_watchlist as
select
    watch_id,
    product_code,
    series,
    product_name,
    color,
    product_url,
    category,
    current_mrp,
    alert_threshold_pct,
    is_active,
    priority,
    notes,
    loaded_at
from raw.watchlist
where is_active = true;

create or replace view staging.stg_price_snapshots as
select
    snapshot_date,
    scrape_run_id,
    watch_id,
    product_code,
    series,
    product_name,
    color,
    mrp,
    source_url,
    is_synthetic,
    ingested_at
from raw.price_snapshots;

drop table if exists mart.price_change_alerts;
drop table if exists mart.price_history;

create table mart.price_history as
with snapshots as (
    select
        s.*,
        lag(s.mrp) over (
            partition by s.watch_id
            order by s.snapshot_date
        ) as previous_mrp,
        lag(s.snapshot_date) over (
            partition by s.watch_id
            order by s.snapshot_date
        ) as previous_snapshot_date
    from staging.stg_price_snapshots s
),
with_changes as (
    select
        snapshot_date,
        previous_snapshot_date,
        scrape_run_id,
        watch_id,
        product_code,
        series,
        product_name,
        color,
        mrp,
        previous_mrp,
        case
            when previous_mrp is null then null
            else mrp - previous_mrp
        end as price_change,
        case
            when previous_mrp is null or previous_mrp = 0 then null
            else round(((mrp - previous_mrp) / previous_mrp) * 100, 2)
        end as pct_change_vs_previous_snapshot,
        source_url,
        is_synthetic,
        ingested_at
    from snapshots
)
select *
from with_changes;

create table mart.price_change_alerts as
select
    h.snapshot_date,
    h.previous_snapshot_date,
    h.watch_id,
    h.product_code,
    h.series,
    h.product_name,
    h.color,
    h.mrp,
    h.previous_mrp,
    h.price_change,
    h.pct_change_vs_previous_snapshot,
    w.alert_threshold_pct,
    w.priority,
    h.source_url,
    h.is_synthetic
from mart.price_history h
join staging.stg_watchlist w
    on h.watch_id = w.watch_id
where h.pct_change_vs_previous_snapshot is not null
  and abs(h.pct_change_vs_previous_snapshot) >= w.alert_threshold_pct;

create index if not exists idx_price_history_watch_date
on mart.price_history (watch_id, snapshot_date);

create index if not exists idx_price_alerts_snapshot
on mart.price_change_alerts (snapshot_date desc);
"""


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


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


def lambda_handler(event, context):
    conn = connect()
    try:
        cur = conn.cursor()
        execute_statements(cur, TRANSFORM_SQL)
        cur.execute("select count(*) from mart.price_history;")
        history_rows = cur.fetchone()[0]
        cur.execute("select count(*) from mart.price_change_alerts;")
        alert_rows = cur.fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "ok",
        "price_history_rows": history_rows,
        "price_change_alert_rows": alert_rows,
    }
