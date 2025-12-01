#!/usr/bin/env python3
"""
Load Parquet fill data into TimescaleDB.

Supports loading from local filesystem or S3 based on DATA_DIR env var.

Usage:
    # Local (default)
    python scripts/load_to_db.py

    # From S3
    DATA_DIR=s3://my-bucket/vigil-data python scripts/load_to_db.py
"""

from tqdm import tqdm

from vigil.config import PARQUET_DIR
from vigil.db import get_db_connection, load_dataframe_to_db
from vigil.transforms import is_s3_path, list_parquet_files, load_parquet

# =============================================================================
# CONFIGURATION
# =============================================================================

# Source directory (default: from config, supports local or S3)
SOURCE_DIR = PARQUET_DIR

# Filter by date (None = load all)
DATE_FILTER = None  # e.g., "20251101"

# Truncate table before loading
TRUNCATE = False

# =============================================================================


def main():
    source_dir = SOURCE_DIR
    is_s3 = is_s3_path(source_dir)

    parquet_files = list_parquet_files(source_dir, DATE_FILTER)
    if not parquet_files:
        print(f"No parquet files in {source_dir}")
        return

    print(f"Found {len(parquet_files)} file(s)")
    print(f"Source: {source_dir} ({'S3' if is_s3 else 'local'})")

    with get_db_connection() as conn:
        if TRUNCATE:
            confirm = input("TRUNCATE fills? Type 'yes': ")
            if confirm != "yes":
                return
            with conn.cursor() as cur:
                cur.execute("TRUNCATE fills")
            conn.commit()
            print("Truncated")

        total = 0
        for pf in tqdm(parquet_files, desc="Loading"):
            try:
                df = load_parquet(pf)
                count = load_dataframe_to_db(df, conn)
                conn.commit()
                total += count
            except Exception as e:
                conn.rollback()
                tqdm.write(f"Error {pf}: {e}")
                raise

        print(f"\nLoaded: {total:,} fills")
    print("Done")


if __name__ == "__main__":
    main()
