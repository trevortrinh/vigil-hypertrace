#!/usr/bin/env python3
"""
Fetch Hyperliquid fill data from S3 and convert to Parquet.

Data mirrors S3 structure locally for sharing between scripts and notebooks:
  data/hl-mainnet-node-data/node_fills_by_block/hourly/{date}/{hour}.parquet
  data/hl-mainnet-node-data/node_fills_by_block/hourly/{date}/{hour}.lz4  (raw, optional)

Skips files that already exist locally.

Usage:
    python scripts/fetch_data.py --earliest --hours 8-23 --keep-raw
    python scripts/fetch_data.py --date 2025-08-01 --hours 0-7
    python scripts/fetch_data.py --start 2025-07-27 --end 2025-07-31
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import boto3
import lz4.frame
import polars as pl
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

# Constants
HL_BUCKET = "hl-mainnet-node-data"
HL_PREFIX = "node_fills_by_block/hourly"
REQUEST_PAYER = {"RequestPayer": "requester"}
EARLIEST_DATE = "2025-07-27"
DATA_DIR = Path("./data")

# Local path mirrors S3: data/{bucket}/{prefix}/{date}/{hour}.parquet
LOCAL_PREFIX = DATA_DIR / HL_BUCKET / HL_PREFIX


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-2"),
    )


def download_hour(s3, date_str: str, hour: int) -> bytes:
    key = f"{HL_PREFIX}/{date_str}/{hour}.lz4"
    response = s3.get_object(Bucket=HL_BUCKET, Key=key, **REQUEST_PAYER)
    return response["Body"].read()


def parse_fills(lz4_data: bytes) -> list[dict]:
    """Parse LZ4 compressed fills data, keeping original S3 field names."""
    decompressed = lz4.frame.decompress(lz4_data)
    lines = decompressed.decode("utf-8").strip().split("\n")

    fills = []
    for line in lines:
        if not line.strip():
            continue
        block = json.loads(line)
        block_time = block.get("block_time")

        for user, fill_data in block.get("events", []):
            # Keep original field names from S3
            fill = {**fill_data, "user": user, "block_time": block_time}
            fills.append(fill)

    return fills


def save_parquet(fills: list[dict], output_path: Path) -> int:
    if not fills:
        return 0

    # infer_schema_length=None scans all rows for consistent types
    df = pl.DataFrame(fills, infer_schema_length=None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(output_path, compression="zstd")
    return len(fills)


def save_raw(lz4_data: bytes, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(lz4_data)


def fetch_hour(s3, date_str: str, hour: int, output_dir: Path, keep_raw: bool = False) -> dict:
    """Fetch single hour, save as parquet (and optionally raw). Skips if exists."""
    stats = {"fills": 0, "bytes": 0, "error": None, "skipped": False}

    parquet_path = output_dir / date_str / f"{hour}.parquet"

    # Skip if already downloaded
    if parquet_path.exists():
        stats["skipped"] = True
        return stats

    try:
        lz4_data = download_hour(s3, date_str, hour)
        stats["bytes"] = len(lz4_data)

        # Save raw if requested (same folder as parquet)
        if keep_raw:
            save_raw(lz4_data, output_dir / date_str / f"{hour}.lz4")

        # Parse and save parquet
        fills = parse_fills(lz4_data)
        stats["fills"] = save_parquet(fills, parquet_path)

    except Exception as e:
        stats["error"] = str(e)

    return stats


def parse_hours(hours_str: str) -> list[int]:
    if "-" in hours_str:
        start, end = map(int, hours_str.split("-"))
        return list(range(start, end + 1))
    elif "," in hours_str:
        return [int(h) for h in hours_str.split(",")]
    return [int(hours_str)]


def date_range(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def main():
    parser = argparse.ArgumentParser(description="Fetch Hyperliquid fills to Parquet")

    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--date", help="Single date (YYYY-MM-DD)")
    date_group.add_argument("--earliest", action="store_true", help=f"Use {EARLIEST_DATE}")
    date_group.add_argument("--start", help="Start date (YYYY-MM-DD)")

    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    parser.add_argument("--hours", default="0-23", help="Hours (e.g., '0-7', '0,12')")
    parser.add_argument("--data-dir", default="./data", help="Base data directory")
    parser.add_argument("--keep-raw", action="store_true", help="Keep raw LZ4 files")

    args = parser.parse_args()

    # Determine dates
    if args.earliest:
        dates = [EARLIEST_DATE.replace("-", "")]
        print(f"Using earliest: {EARLIEST_DATE}")
    elif args.date:
        dates = [args.date.replace("-", "")]
    elif args.start:
        if not args.end:
            print("Error: --end required with --start")
            sys.exit(1)
        dates = date_range(args.start, args.end)
    else:
        print(f"Error: specify --date, --earliest, or --start/--end")
        sys.exit(1)

    hours = parse_hours(args.hours)
    data_dir = Path(args.data_dir)

    # Output mirrors S3 structure: data/{bucket}/{prefix}/{date}/{hour}.parquet
    output_dir = data_dir / HL_BUCKET / HL_PREFIX

    print(f"Dates: {len(dates)}, Hours: {hours[0]}-{hours[-1]}")
    print(f"Output: {output_dir}")
    if args.keep_raw:
        print(f"Raw LZ4 files will be saved alongside parquet")

    s3 = get_s3_client()
    total_fills = 0
    total_bytes = 0
    skipped = 0
    errors = []

    for date_str in dates:
        pbar = tqdm(hours, desc=date_str, leave=False)
        for hour in pbar:
            stats = fetch_hour(s3, date_str, hour, output_dir, args.keep_raw)
            if stats["skipped"]:
                skipped += 1
                pbar.set_postfix({"status": "skipped"})
            elif stats["error"]:
                errors.append(f"{date_str}/{hour}: {stats['error']}")
                pbar.set_postfix({"error": stats["error"][:20]})
            else:
                total_fills += stats["fills"]
                total_bytes += stats["bytes"]
                pbar.set_postfix({"fills": f"{stats['fills']:,}"})

        tqdm.write(f"  {date_str}: {total_fills:,} fills")

    print()
    print(f"Total: {total_fills:,} fills, {total_bytes/1024/1024:.1f} MB downloaded")
    if skipped:
        print(f"Skipped: {skipped} files (already exist)")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors[:3]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
