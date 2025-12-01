#!/usr/bin/env python3
"""
Fetch Hyperliquid fill data from S3 and convert to Parquet.

Usage:
    python scripts/fetch_data.py
"""

from tqdm import tqdm

from vigil.config import LOCAL_PARQUET_DIR
from vigil.s3 import download_hour, get_s3_client, list_available_dates, list_available_hours
from vigil.transforms import parse_fills, save_parquet

# =============================================================================
# CONFIGURATION
# =============================================================================

# Fetch all available data (set to True to discover and fetch everything)
FETCH_ALL = False

# Or specify explicit dates (ignored if FETCH_ALL=True)
DATES = ["20251101"]

# Hours to fetch (0-23)
HOURS = list(range(24))

# Keep raw LZ4 files alongside parquet
KEEP_RAW = False

# =============================================================================


def save_raw(lz4_data: bytes, output_path):
    """Save raw LZ4 file alongside parquet."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(lz4_data)


def fetch_hour(s3, date_str: str, hour: int, output_dir, keep_raw: bool = False) -> dict:
    """Fetch single hour, save as parquet. Skips if exists."""
    stats = {"fills": 0, "bytes": 0, "error": None, "skipped": False}

    parquet_path = output_dir / date_str / f"{hour}.parquet"

    if parquet_path.exists():
        stats["skipped"] = True
        return stats

    try:
        lz4_data = download_hour(s3, date_str, hour)
        stats["bytes"] = len(lz4_data)

        if keep_raw:
            save_raw(lz4_data, output_dir / date_str / f"{hour}.lz4")

        fills = parse_fills(lz4_data)
        stats["fills"] = save_parquet(fills, parquet_path)

    except Exception as e:
        stats["error"] = str(e)

    return stats


def main():
    s3 = get_s3_client()
    output_dir = LOCAL_PARQUET_DIR

    # Determine dates to fetch
    if FETCH_ALL:
        print("Listing available dates...")
        dates = list_available_dates(s3)
        print(f"Found {len(dates)} dates")
    else:
        dates = DATES

    print(f"Dates: {len(dates)}, Hours: {HOURS[0]}-{HOURS[-1]}")
    print(f"Output: {output_dir}")

    total_fills = 0
    total_bytes = 0
    skipped = 0
    errors = []

    for date_str in tqdm(dates, desc="Dates"):
        # Get available hours for this date
        if FETCH_ALL:
            hours = [h for h in list_available_hours(s3, date_str) if h in HOURS]
        else:
            hours = HOURS

        for hour in hours:
            stats = fetch_hour(s3, date_str, hour, output_dir, KEEP_RAW)
            if stats["skipped"]:
                skipped += 1
            elif stats["error"]:
                errors.append(f"{date_str}/{hour}: {stats['error']}")
            else:
                total_fills += stats["fills"]
                total_bytes += stats["bytes"]

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
