from db import connect


QUERY = """
select
    snapshot_date,
    watch_id,
    product_code,
    series,
    product_name,
    color,
    previous_mrp,
    mrp,
    pct_change_vs_previous_snapshot,
    alert_threshold_pct
from mart.price_change_alerts
order by snapshot_date desc, abs(pct_change_vs_previous_snapshot) desc
limit 25;
"""


def main():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(QUERY)
            rows = cur.fetchall()

    if not rows:
        print("No alert rows found. Run dbt first, or lower alert thresholds.")
        return

    headers = [
        "date",
        "watch_id",
        "sku",
        "series",
        "product",
        "color",
        "previous",
        "current",
        "pct_change",
        "threshold",
    ]
    print("\t".join(headers))
    for row in rows:
        print("\t".join("" if value is None else str(value) for value in row))


if __name__ == "__main__":
    main()
