import os
from pathlib import Path

import boto3
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
load_dotenv(ROOT / ".env")


def upload_file(s3, bucket: str, local_path: Path, key: str):
    s3.upload_file(str(local_path), bucket, key)
    print(f"s3://{bucket}/{key}")


def main():
    bucket = os.environ["S3_BUCKET"]
    region = os.environ.get("AWS_REGION", "ap-south-1")
    s3 = boto3.client("s3", region_name=region)

    upload_file(
        s3,
        bucket,
        DATA_DIR / "jaquar_price_watchlist_50.csv",
        "watchlist/jaquar_price_watchlist_50.csv",
    )
    upload_file(
        s3,
        bucket,
        DATA_DIR / "jaquar_price_history_seed_synthetic.csv",
        "seed/jaquar_price_history_seed_synthetic.csv",
    )


if __name__ == "__main__":
    main()
