# Extract Prices Lambda

Placeholder for the AWS Lambda version of the existing Jaquar scraper.

Planned behavior:

1. Read active watchlist rows from S3 or Google Sheets.
2. Fetch each `product_url`.
3. Extract CSRF token and swatches.
4. POST to Jaquar's variant endpoint.
5. Write raw JSON snapshot to `s3://<bucket>/raw/jaquar/dt=<date>/run=<run_id>.json`.

The local seed workflow is built first so the warehouse, dbt layer, and API contract are proven before deploying this function.
