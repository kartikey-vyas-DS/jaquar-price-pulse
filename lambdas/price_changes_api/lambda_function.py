import json
import os
import ssl
from decimal import Decimal
from typing import Any

import pg8000.dbapi


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


def as_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def as_decimal(value: str | None, default: Decimal) -> Decimal:
    try:
        return Decimal(value) if value is not None else default
    except Exception:
        return default


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",
        },
        "body": json.dumps(body, default=json_safe),
    }


def lambda_handler(event, context):
    query = event.get("queryStringParameters") or {}
    days = as_int(query.get("days"), default=14, minimum=1, maximum=365)
    limit = as_int(query.get("limit"), default=50, minimum=1, maximum=200)
    min_pct = as_decimal(query.get("min_pct"), default=Decimal("0"))

    sql = """
    with max_snapshot as (
        select max(snapshot_date) as max_date
        from mart.price_change_alerts
    )
    select
        a.snapshot_date::text,
        a.previous_snapshot_date::text,
        a.watch_id,
        a.product_code,
        a.series,
        a.product_name,
        a.color,
        a.previous_mrp,
        a.mrp,
        a.price_change,
        a.pct_change_vs_previous_snapshot,
        a.alert_threshold_pct,
        a.priority,
        a.source_url,
        a.is_synthetic
    from mart.price_change_alerts a
    cross join max_snapshot m
    where a.snapshot_date >= m.max_date - (%s * interval '1 day')
      and abs(a.pct_change_vs_previous_snapshot) >= %s
    order by a.snapshot_date desc, abs(a.pct_change_vs_previous_snapshot) desc
    limit %s;
    """

    columns = [
        "snapshot_date",
        "previous_snapshot_date",
        "watch_id",
        "product_code",
        "series",
        "product_name",
        "color",
        "previous_mrp",
        "mrp",
        "price_change",
        "pct_change_vs_previous_snapshot",
        "alert_threshold_pct",
        "priority",
        "source_url",
        "is_synthetic",
    ]

    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, (days, min_pct, limit))
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()

    return response(
        200,
        {
            "status": "ok",
            "filters": {
                "days": days,
                "limit": limit,
                "min_pct": float(min_pct),
            },
            "count": len(rows),
            "results": rows,
        },
    )
