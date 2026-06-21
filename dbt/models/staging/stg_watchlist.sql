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
where is_active = true
