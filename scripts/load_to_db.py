#!/usr/bin/env python3
"""Load Parquet fill data into TimescaleDB."""

import time

from tqdm import tqdm

from vigil.config import PARQUET_DIR
from vigil.db import get_db_connection, load_dataframe_to_db
from vigil.transforms import is_s3_path, list_parquet_files, load_parquet

# =============================================================================
# CONFIGURATION
# =============================================================================

SOURCE_DIR = PARQUET_DIR
DATE_FILTER = None  # e.g., "20251101"

# =============================================================================


def main():
    files = list_parquet_files(SOURCE_DIR, DATE_FILTER)
    if not files:
        print(f"No parquet files in {SOURCE_DIR}")
        return

    print(f"Source: {SOURCE_DIR} ({'S3' if is_s3_path(SOURCE_DIR) else 'local'})")
    print(f"Found {len(files)} file(s)")

    total_rows = 0
    failed = []

    with get_db_connection() as conn:
        for filepath in tqdm(files, desc="Loading", unit="file"):
            # Extract date/hour for logging
            parts = filepath.split("/")
            file_id = f"{parts[-2]}/{parts[-1]}"

            try:
                t0 = time.time()
                df = load_parquet(filepath)
                t1 = time.time()
                count = load_dataframe_to_db(df, conn)
                t2 = time.time()
                conn.commit()
                t3 = time.time()
                total_rows += count
                tqdm.write(f"OK: {file_id} | load:{t1-t0:.1f}s db:{t2-t1:.1f}s commit:{t3-t2:.1f}s | {count:,} rows")
            except Exception as e:
                conn.rollback()
                failed.append((filepath, str(e)))
                tqdm.write(f"FAIL: {file_id} - {e}")

    print(f"\nLoaded: {total_rows:,} rows")
    if failed:
        print(f"\nFailed ({len(failed)}):")
        for path, err in failed:
            print(f"  {path}: {err}")


if __name__ == "__main__":
    main()
