import csv
from pathlib import Path

from db import ROOT, connect


DATA_DIR = ROOT / "data"
WATCHLIST_CSV = DATA_DIR / "jaquar_price_watchlist_50.csv"
HISTORY_CSV = DATA_DIR / "jaquar_price_history_seed_synthetic.csv"
SCHEMA_SQL = ROOT / "sql" / "001_schema.sql"


def as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def load_watchlist(cur):
    with WATCHLIST_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

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


def load_history(cur):
    with HISTORY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

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


def main():
    if not WATCHLIST_CSV.exists():
        raise FileNotFoundError(WATCHLIST_CSV)
    if not HISTORY_CSV.exists():
        raise FileNotFoundError(HISTORY_CSV)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
            watchlist_rows = load_watchlist(cur)
            history_rows = load_history(cur)
        conn.commit()

    print(f"Loaded {watchlist_rows} watchlist rows")
    print(f"Loaded {history_rows} historical snapshot rows")


if __name__ == "__main__":
    main()

