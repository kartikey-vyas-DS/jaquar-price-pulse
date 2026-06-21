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
