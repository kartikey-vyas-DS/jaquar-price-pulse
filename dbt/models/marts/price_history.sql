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
    from {{ ref('stg_price_snapshots') }} s
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
from with_changes
