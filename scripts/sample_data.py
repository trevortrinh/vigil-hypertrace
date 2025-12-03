#!/usr/bin/env python3
"""
Sample fills data for local analysis pipeline development.

Simple approach: just grab N rows. No expensive GROUP BY on 1.9B rows.
Once we build the pipeline, we push the schema to TimescaleDB and let it aggregate.
"""

import sys
from pathlib import Path

import polars as pl

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vigil.db import execute_query, get_db_connection


def main():
    limit = 500_000
    output_path = Path("data/sample_fills.parquet")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to database and fetching {limit:,} fills...")
    conn = get_db_connection()

    try:
        # Simple limit query - no aggregation, fast
        # Cast liquidation to TEXT to avoid schema inference issues
        df = execute_query(
            f"""
            SELECT
                time, user_address, coin, px, sz, side, dir,
                start_position, closed_pnl, fee, crossed,
                hash, oid, tid, block_time, fee_token,
                twap_id, builder_fee, cloid, builder,
                liquidation::TEXT as liquidation
            FROM fills
            LIMIT {limit}
            """,
            conn,
        )

        # Save
        df.write_parquet(output_path)
        print(f"Saved to {output_path}")

        # Summary
        print("\n=== Sample Summary ===")
        print(f"Total fills: {len(df):,}")
        print(f"Unique traders: {df['user_address'].n_unique()}")
        print(f"Unique coins: {df['coin'].n_unique()}")

        # Time range
        min_time = df["time"].min()
        max_time = df["time"].max()
        print(f"Time range: {min_time} - {max_time}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
