#!/usr/bin/env python3
"""
Load sample parquet data into local TimescaleDB.

Usage:
1. Run `just sample-data` to pull sample from cloud DB
2. Run `just db-local-up` to start local TimescaleDB
3. Run `just db-local-migrate` to create tables
4. Run `just load-sample-local` (this script)
"""

import io
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vigil.db import get_db_connection

# DB columns in order
DB_COLUMNS = [
    "time", "user_address", "coin", "px", "sz", "side", "dir",
    "start_position", "closed_pnl", "fee", "crossed",
    "hash", "oid", "tid", "block_time", "fee_token",
    "twap_id", "builder_fee", "cloid", "builder", "liquidation"
]


def main():
    sample_path = Path("data/sample_fills.parquet")

    if not sample_path.exists():
        print(f"Sample file not found: {sample_path}")
        print("Run `just sample-data` first to pull sample from cloud DB")
        sys.exit(1)

    print(f"Loading {sample_path}...")
    df = pl.read_parquet(sample_path)
    print(f"Loaded {len(df):,} rows, {len(df.columns)} columns")

    # Ensure all columns exist (add nulls for missing)
    for col in DB_COLUMNS:
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).alias(col))

    # Select columns in correct order
    df = df.select(DB_COLUMNS)

    # Convert crossed boolean to PostgreSQL format
    df = df.with_columns(
        pl.when(pl.col("crossed") == True)
        .then(pl.lit("t"))
        .when(pl.col("crossed") == False)
        .then(pl.lit("f"))
        .otherwise(pl.lit(None))
        .alias("crossed")
    )

    print("Connecting to database...")
    conn = get_db_connection()

    try:
        # Clear existing data
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE fills")
            conn.commit()
        print("Cleared existing fills")

        # Write to CSV buffer
        csv_buffer = io.BytesIO()
        df.write_csv(csv_buffer, separator="\t", null_value="\\N")
        csv_data = csv_buffer.getvalue().decode("utf-8")

        # COPY to database
        with conn.cursor() as cur:
            with cur.copy(
                f"COPY fills ({','.join(DB_COLUMNS)}) FROM STDIN WITH (FORMAT text, HEADER true)"
            ) as copy:
                copy.write(csv_data)

        conn.commit()
        print(f"Loaded {len(df):,} rows into fills table")

        # Verify
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM fills")
            count = cur.fetchone()[0]
        print(f"Verified: {count:,} rows in fills table")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
