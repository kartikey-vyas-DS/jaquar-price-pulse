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
from raw.price_snapshots
