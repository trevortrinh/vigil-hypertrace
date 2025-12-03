#!/usr/bin/env python3
"""
Sample fills data for local analysis pipeline development.

Samples directly from S3 parquet files (not the cloud DB) to get clean data.
"""

import sys
from pathlib import Path

import polars as pl

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vigil.transforms import list_parquet_files, load_parquet
from vigil.config import PARQUET_DIR
from vigil.db import PARQUET_TO_DB


def main():
    limit = 500_000
    output_path = Path("data/sample_fills.parquet")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[S3] Sampling {limit:,} fills from parquet files...")

    # Get recent parquet files from S3
    files = list_parquet_files(PARQUET_DIR, None)
    print(f"Found {len(files)} parquet files")

    # Sample from the most recent files
    dfs = []
    rows_collected = 0

    for filepath in reversed(files):  # Start from most recent
        if rows_collected >= limit:
            break

        df = load_parquet(filepath)

        # Ensure all columns exist
        for col in PARQUET_TO_DB.keys():
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).alias(col))

        # Select and rename to DB columns
        df = df.select(list(PARQUET_TO_DB.keys())).rename(PARQUET_TO_DB)

        # Convert liquidation struct to JSON string
        liq_dtype = df["liquidation"].dtype
        if liq_dtype != pl.String and liq_dtype != pl.Null:
            df = df.with_columns(
                pl.when(pl.col("liquidation").is_null())
                .then(pl.lit(None))
                .otherwise(pl.col("liquidation").struct.json_encode())
                .alias("liquidation")
            )
        elif liq_dtype == pl.Null:
            df = df.with_columns(pl.lit(None).cast(pl.String).alias("liquidation"))

        dfs.append(df)
        rows_collected += len(df)
        print(f"  {filepath.split('/')[-2]}/{filepath.split('/')[-1]}: {len(df):,} rows (total: {rows_collected:,})")

    # Combine and limit
    combined = pl.concat(dfs)
    if len(combined) > limit:
        combined = combined.head(limit)

    # Save
    combined.write_parquet(output_path)
    print(f"\nSaved to {output_path}")

    # Summary
    print("\n=== Sample Summary ===")
    print(f"Total fills: {len(combined):,}")
    print(f"Unique traders: {combined['user_address'].n_unique()}")
    print(f"Unique coins: {combined['coin'].n_unique()}")

    # Time range
    min_time = combined["time"].min()
    max_time = combined["time"].max()
    print(f"Time range: {min_time} - {max_time}")

    # Liquidation stats
    liq_count = combined.filter(pl.col("liquidation").is_not_null()).height
    print(f"Liquidations: {liq_count:,}")


if __name__ == "__main__":
    main()
