#!/usr/bin/env python3
"""Load Parquet fill data into TimescaleDB."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from vigil.config import PARQUET_DIR
from vigil.db import get_db_connection, load_dataframe_to_db
from vigil.transforms import is_s3_path, list_parquet_files, load_parquet

# =============================================================================
# CONFIGURATION
# =============================================================================

SOURCE_DIR = PARQUET_DIR
DATE_FILTER = None  # e.g., "20251101"
WORKERS = 2 # Parallel workers

# =============================================================================


def load_file(filepath: str) -> tuple[str, int, float, float, str | None]:
    """Load a single file. Returns (file_id, rows, load_time, db_time, error)."""
    parts = filepath.split("/")
    file_id = f"{parts[-2]}/{parts[-1]}"

    try:
        t0 = time.time()
        df = load_parquet(filepath)
        t1 = time.time()

        with get_db_connection() as conn:
            count = load_dataframe_to_db(df, conn)
            conn.commit()
        t2 = time.time()

        return (file_id, count, t1 - t0, t2 - t1, None)
    except Exception as e:
        return (file_id, 0, 0, 0, str(e))


def main():
    files = list_parquet_files(SOURCE_DIR, DATE_FILTER)
    if not files:
        print(f"No parquet files in {SOURCE_DIR}")
        return

    print(f"Source: {SOURCE_DIR} ({'S3' if is_s3_path(SOURCE_DIR) else 'local'})")
    print(f"Found {len(files)} file(s)")
    print(f"Workers: {WORKERS}")

    total_rows = 0
    failed = []

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(load_file, f): f for f in files}

        for future in tqdm(as_completed(futures), total=len(files), desc="Loading", unit="file"):
            file_id, count, load_time, db_time, error = future.result()
            if error:
                failed.append((file_id, error))
                tqdm.write(f"FAIL: {file_id} - {error}")
            else:
                total_rows += count
                tqdm.write(f"OK: {file_id} | load:{load_time:.1f}s db:{db_time:.1f}s | {count:,} rows")

    print(f"\nLoaded: {total_rows:,} rows")
    if failed:
        print(f"\nFailed ({len(failed)}):")
        for path, err in failed:
            print(f"  {path}: {err}")


if __name__ == "__main__":
    main()
