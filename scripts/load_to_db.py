#!/usr/bin/env python3
"""
Load Parquet fill data into TimescaleDB.

Usage:
    python scripts/load_to_db.py
"""

from pathlib import Path

from tqdm import tqdm

from vigil.config import LOCAL_PARQUET_DIR
from vigil.db import get_db_connection, load_parquet_to_db

# =============================================================================
# CONFIGURATION
# =============================================================================

# Source directory (default: local parquet dir)
SOURCE_DIR = LOCAL_PARQUET_DIR

# Filter by date (None = load all)
DATE_FILTER = None  # e.g., "20251101"

# Truncate table before loading
TRUNCATE = False

# =============================================================================


def get_parquet_files(source_dir: Path, date_filter: str = None) -> list[Path]:
    """Find parquet files, optionally filtered by date folder."""
    files = []
    for parquet_file in sorted(source_dir.rglob("*.parquet")):
        if date_filter:
            if parquet_file.parent.name != date_filter:
                continue
        files.append(parquet_file)
    return files


def main():
    source_dir = Path(SOURCE_DIR) if isinstance(SOURCE_DIR, str) else SOURCE_DIR

    if not source_dir.exists():
        print(f"Error: {source_dir} not found")
        return

    parquet_files = get_parquet_files(source_dir, DATE_FILTER)
    if not parquet_files:
        print(f"No parquet files in {source_dir}")
        return

    print(f"Found {len(parquet_files)} file(s)")
    print(f"Source: {source_dir}")

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
                count = load_parquet_to_db(pf, conn)
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
