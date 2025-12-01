#!/usr/bin/env python3
"""
Fetch Hyperliquid fill data from S3 and convert to Parquet.

Supports writing to local filesystem or S3 based on DATA_DIR env var.

Usage:
    # Local (default)
    python scripts/fetch_data.py

    # To S3
    DATA_DIR=s3://my-bucket/vigil-data python scripts/fetch_data.py
"""

from tqdm import tqdm

from vigil.config import HL_BUCKET, HL_PREFIX, PARQUET_DIR
from vigil.s3 import download, get_s3_client, list_files, list_prefixes
from vigil.transforms import is_s3_path, parquet_exists, parse_fills, save_parquet

# =============================================================================
# CONFIGURATION
# =============================================================================

# Fetch all available data (set to True to discover and fetch everything)
FETCH_ALL = True

# Or specify explicit dates (ignored if FETCH_ALL=True)
DATES = ["20251101"]

# Hours to fetch (0-23)
HOURS = list(range(24))

# Output directory (from config, supports local or S3)
OUTPUT_DIR = PARQUET_DIR

# =============================================================================


def get_parquet_path(base_dir: str, date_str: str, hour: int) -> str:
    """Build parquet path for local or S3."""
    hour_str = f"{hour:02d}"
    if is_s3_path(base_dir):
        return f"{base_dir.rstrip('/')}/{date_str}/{hour_str}.parquet"
    else:
        from pathlib import Path
        return str(Path(base_dir) / date_str / f"{hour_str}.parquet")


def main():
    s3 = get_s3_client()
    output_dir = OUTPUT_DIR
    is_s3 = is_s3_path(output_dir)

    # Determine dates to fetch
    if FETCH_ALL:
        print("Listing available dates...")
        prefixes = list_prefixes(HL_BUCKET, f"{HL_PREFIX}/", s3)
        dates = sorted(p.rstrip("/").split("/")[-1] for p in prefixes)
        print(f"Found {len(dates)} dates")
    else:
        dates = DATES

    print(f"Dates: {len(dates)}, Hours: {HOURS[0]}-{HOURS[-1]}")
    print(f"Output: {output_dir} ({'S3' if is_s3 else 'local'})")

    total_fills = 0
    total_bytes = 0
    skipped = 0
    errors = []

    for date_str in tqdm(dates, desc="Dates"):
        # Get available hours for this date
        if FETCH_ALL:
            files = list_files(HL_BUCKET, f"{HL_PREFIX}/{date_str}/", s3)
            available = [int(k.split("/")[-1].replace(".lz4", "")) for k, _ in files]
            hours = [h for h in available if h in HOURS]
        else:
            hours = HOURS

        for hour in tqdm(hours, desc=f"  {date_str}", leave=False):
            parquet_path = get_parquet_path(output_dir, date_str, hour)
            if parquet_exists(parquet_path):
                skipped += 1
                continue

            try:
                key = f"{HL_PREFIX}/{date_str}/{hour}.lz4"
                lz4_data = download(HL_BUCKET, key, s3)
                total_bytes += len(lz4_data)

                fills = parse_fills(lz4_data)
                total_fills += save_parquet(fills, parquet_path)
            except Exception as e:
                errors.append(f"{date_str}/{hour}: {e}")

    print()
    print(f"Total: {total_fills:,} fills, {total_bytes / 1024 / 1024:.1f} MB downloaded")
    if skipped:
        print(f"Skipped: {skipped} files (already exist)")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors[:5]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
