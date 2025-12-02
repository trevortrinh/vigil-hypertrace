#!/usr/bin/env python3
"""Inspect parquet file schema to find nested columns."""

import sys
import polars as pl

from vigil.transforms import load_parquet

# Check a specific file or default
FILE = sys.argv[1] if len(sys.argv) > 1 else "s3://vigil-contract-data/20250727/09.parquet"

print(f"Inspecting: {FILE}\n")

df = load_parquet(FILE)

print("Schema:")
print("-" * 50)
for col in df.columns:
    dtype = df[col].dtype
    nested = "← NESTED" if "Struct" in str(dtype) or "List" in str(dtype) else ""
    print(f"  {col}: {dtype} {nested}")

print(f"\nRows: {len(df):,}")
print(f"Columns: {len(df.columns)}")

# Show sample of nested columns
for col in df.columns:
    dtype_str = str(df[col].dtype)
    if "Struct" in dtype_str or "List" in dtype_str:
        print(f"\nSample of '{col}':")
        print(df[col].head(3))
