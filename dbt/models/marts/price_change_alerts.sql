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
from {{ ref('price_history') }} h
join {{ ref('stg_watchlist') }} w
    on h.watch_id = w.watch_id
where h.pct_change_vs_previous_snapshot is not null
  and abs(h.pct_change_vs_previous_snapshot) >= w.alert_threshold_pct
