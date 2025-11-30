#!/usr/bin/env python3
"""
Load Parquet fill data into TimescaleDB.

Reads hourly parquet files from shared data directory:
  data/hl-mainnet-node-data/node_fills_by_block/hourly/{YYYYMMDD}/{hour}.parquet

Usage:
    python scripts/load_to_db.py                    # Load all
    python scripts/load_to_db.py --date 20250727    # Load specific date
    python scripts/load_to_db.py --truncate         # Wipe and reload
"""

import argparse
import io
import os
import sys
from pathlib import Path

import polars as pl
import psycopg
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:password@localhost:5435/vigil"
)

# Raw column names from S3 (matching parquet files)
# Some need quoting for SQL (reserved words, camelCase)
FILL_COLUMNS = [
    "time", "user", "coin", "px", "sz", "side", "dir", "startPosition",
    "closedPnl", "fee", "crossed", "hash", "oid", "tid", "block_time",
    "feeToken", "twapId", "builderFee", "cloid", "builder", "liquidation",
]

# SQL-safe column names (quoted where needed)
SQL_COLUMNS = [
    "time", '"user"', "coin", "px", "sz", "side", "dir", '"startPosition"',
    '"closedPnl"', "fee", "crossed", "hash", "oid", "tid", "block_time",
    '"feeToken"', '"twapId"', '"builderFee"', "cloid", "builder", "liquidation",
]


def get_parquet_files(source_dir: Path, date_filter: str = None) -> list[Path]:
    """Find parquet files, optionally filtered by date folder."""
    files = []
    for parquet_file in sorted(source_dir.rglob("*.parquet")):
        if date_filter:
            # Date filter is YYYYMMDD format, parent folder should match
            if parquet_file.parent.name != date_filter:
                continue
        files.append(parquet_file)
    return files


def load_parquet_to_db(parquet_path: Path, conn) -> int:
    """Load parquet file into DB using COPY."""
    df = pl.read_parquet(parquet_path)
    if df.is_empty():
        return 0

    # Ensure columns exist
    for col in FILL_COLUMNS:
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).alias(col))
    df = df.select(FILL_COLUMNS)

    # Build CSV for COPY
    csv_buffer = io.StringIO()
    csv_buffer.write("\t".join(FILL_COLUMNS) + "\n")

    for row in df.iter_rows():
        values = []
        for val in row:
            if val is None:
                values.append("\\N")
            elif isinstance(val, bool):
                values.append("t" if val else "f")
            else:
                values.append(str(val).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n"))
        csv_buffer.write("\t".join(values) + "\n")

    csv_buffer.seek(0)

    with conn.cursor() as cur:
        with cur.copy(f"COPY fills ({','.join(SQL_COLUMNS)}) FROM STDIN WITH (FORMAT text, HEADER true)") as copy:
            while data := csv_buffer.read(8192):
                copy.write(data)

    return len(df)


def main():
    parser = argparse.ArgumentParser(description="Load Parquet into TimescaleDB")
    parser.add_argument(
        "--source",
        default="./data/hl-mainnet-node-data/node_fills_by_block/hourly",
        help="Parquet directory",
    )
    parser.add_argument("--date", help="Only load specific date (YYYYMMDD)")
    parser.add_argument("--truncate", action="store_true", help="Truncate before loading")
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"Error: {source_dir} not found")
        sys.exit(1)

    parquet_files = get_parquet_files(source_dir, args.date)
    if not parquet_files:
        print(f"No parquet files in {source_dir}")
        sys.exit(1)

    print(f"Found {len(parquet_files)} file(s)")
    print(f"DB: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")

    with psycopg.connect(DATABASE_URL) as conn:
        conn.autocommit = False

        if args.truncate:
            confirm = input("TRUNCATE fills? Type 'yes': ")
            if confirm != "yes":
                sys.exit(1)
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
