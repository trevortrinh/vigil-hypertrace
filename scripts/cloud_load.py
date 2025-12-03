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
WORKERS = 2  # Parallel workers

# =============================================================================


def get_loaded_files(conn) -> set[str]:
    """Get file IDs that have been successfully loaded."""
    with conn.cursor() as cur:
        cur.execute("SELECT file_id FROM load_progress")
        return {row[0] for row in cur.fetchall()}


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
            # Track progress in same transaction
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO load_progress (file_id, rows_loaded) VALUES (%s, %s) ON CONFLICT (file_id) DO NOTHING",
                    (file_id, count)
                )
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

    print(f"[CLOUD DB] Loading to TimescaleDB...")
    print(f"Source: {SOURCE_DIR} ({'S3' if is_s3_path(SOURCE_DIR) else 'local'})")
    print(f"Found {len(files)} file(s)")

    # Get already loaded files (requires 003_load_tracking.sql migration)
    with get_db_connection() as conn:
        loaded_files = get_loaded_files(conn)
        if loaded_files:
            print(f"Already loaded: {len(loaded_files)} file(s)")

    # Filter out already loaded files
    def get_file_id(path: str) -> str:
        parts = path.split("/")
        return f"{parts[-2]}/{parts[-1]}"

    files_to_load = [f for f in files if get_file_id(f) not in loaded_files]

    if not files_to_load:
        print("All files already loaded!")
        return

    print(f"To load: {len(files_to_load)} file(s)")
    print(f"Workers: {WORKERS}")

    total_rows = 0
    failed = []

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(load_file, f): f for f in files_to_load}

        for future in tqdm(as_completed(futures), total=len(files_to_load), desc="Loading", unit="file"):
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
