#!/usr/bin/env python3
"""
Load Parquet fill data into TimescaleDB.

Usage:
    python scripts/load_to_db.py
"""

from tqdm import tqdm

from vigil.config import PARQUET_DIR
from vigil.db import get_db_connection, load_dataframe_to_db
from vigil.transforms import is_s3_path, list_parquet_files, load_parquet

# =============================================================================
# CONFIGURATION
# =============================================================================

# Source directory (supports local or S3)
SOURCE_DIR = PARQUET_DIR

# Filter by date (None = load all)
DATE_FILTER = None  # e.g., "20251101"

# =============================================================================


def main():
    source_dir = SOURCE_DIR
    is_s3 = is_s3_path(source_dir)

    files = list_parquet_files(source_dir, DATE_FILTER)
    if not files:
        print(f"No parquet files in {source_dir}")
        return

    print(f"Source: {source_dir} ({'S3' if is_s3 else 'local'})")
    print(f"Found {len(files)} file(s)")

    total_rows = 0
    failed = []

    with get_db_connection() as conn:
        for filepath in tqdm(files, desc="Loading", unit="file"):
            try:
                df = load_parquet(filepath)
                count = load_dataframe_to_db(df, conn)
                conn.commit()
                total_rows += count
            except Exception as e:
                conn.rollback()
                failed.append((filepath, str(e)))
                tqdm.write(f"Error: {e}")

    print(f"\nLoaded: {total_rows:,} rows")

    if failed:
        print(f"\nFailed files ({len(failed)}):")
        for path, err in failed:
            print(f"  {path}: {err}")


if __name__ == "__main__":
    main()
