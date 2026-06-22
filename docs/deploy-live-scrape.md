# Deploy Live Scrape Lambda

This project keeps `jpp-load-seed` as a bootstrap/backfill utility. The scheduled production workflow should call the live scraper first, then transform prices.

## Lambda

Create or update a Lambda named `jpp-scrape-jaquar-prices`.

Runtime:

- Python 3.12
- x86_64
- Same VPC/subnets as the RDS database
- Security group: `jpp-lambda-db-sg`
- Timeout: 10-15 minutes
- Memory: 512 MB

Environment variables:

```env
S3_BUCKET=jaquar-price-pulse-kvs-20260621
WATCHLIST_KEY=watchlist/jaquar_price_watchlist_50.csv
PGHOST=jaquar-price-pulse-db.c962wgiycsyj.ap-south-1.rds.amazonaws.com
PGPORT=5432
PGDATABASE=jaquar_price_pulse
PGUSER=jppadmin
PGPASSWORD=<database-password>
SCRAPE_LIMIT=50
MAX_FAILURE_RATE=0.50
```

Package locally:

```powershell
.\scripts\package_scrape_jaquar_lambda.ps1 -Python .\.venv\Scripts\python.exe
```

Upload:

```text
build/scrape_jaquar_prices_lambda.zip
```

## Step Functions

Replace the old daily state-machine shape:

```text
LoadSeedData -> TransformPrices
```

with:

```text
ScrapeJaquarPrices -> TransformPrices
```

Keep `jpp-load-seed` available for initial bootstrap or manual re-backfill only. Do not run it daily after live snapshots start, because it truncates and reloads the seeded history.

## Smoke Test

Use a small Lambda test event first:

```json
{
  "run_id": "manual-smoke"
}
```

Temporarily set `SCRAPE_LIMIT=3` for the first run. Expected result:

```json
{
  "status": "ok",
  "matched_rows": 3,
  "failed_rows": 0
}
```

Then run `jpp-transform-prices` and call the API endpoint again.
