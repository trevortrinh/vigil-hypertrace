# Data Ingestion Strategy

## Overview

Copy Hyperliquid fill data from their public S3 to your own S3, transforming to Parquet for efficient DB loading and analysis.

## Source Data

```
s3://hl-mainnet-node-data/node_fills_by_block/hourly/
├── 20250727/  (Jul 27, 2025 - start)
│   ├── 0.lz4   (~15-25 MB each)
│   ├── 1.lz4
│   └── ... (24 files per day)
└── 20251130/  (present)
```

- **Total:** ~126 days, ~75 GB compressed
- **Format:** LZ4-compressed JSON lines
- **Region:** us-east-1

---

## Recommended Approach: Parquet Transform

### Why Parquet Over Raw Sync

| Factor | Raw .lz4 (DataSync) | Parquet |
|--------|---------------------|---------|
| Storage size | ~75 GB | ~50-60 GB (smaller) |
| DB load speed | Slow (parse JSON first) | Fast (columnar bulk load) |
| Schema | Implicit | Explicit + typed |
| Query without DB | Need to parse each time | DuckDB instant |
| Reprocessing | Always from scratch | Already done |

### Workflow Comparison

```
DataSync approach:
  HL S3 → Your S3 (raw) → Parse JSON → Transform → Load DB
                          └── you still do this work ──┘

Parquet approach:
  HL S3 → Transform → Your S3 (parquet) → Load DB
          └── do once ─┘                   └── fast ─┘
```

---

## Architecture

```
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│  HL S3           │─ stream ─│  EC2 us-east-1   │─ stream ─│  Your S3         │
│  (us-east-1)     │  (free)  │  (decompress +   │  (free)  │  (us-east-1)     │
│                  │          │  transform)      │          │                  │
└──────────────────┘          └──────────────────┘          └──────────────────┘
                                     │
                               Parquet output
                              (5-10x smaller)
```

### Why Same-Region Processing

- **No egress fees** - S3-to-S3 in same region is free
- **~10 Gbps bandwidth** - EC2 to S3 in same region
- **Parallel processing** - process 24 hours simultaneously
- **Stream, don't batch** - no local disk bottleneck

---

## Output Structure

```
s3://your-vigil-bucket/
├── processed/
│   └── fills/
│       ├── date=2025-07-27/
│       │   ├── hour=00.parquet
│       │   ├── hour=01.parquet
│       │   └── ...
│       ├── date=2025-07-28/
│       └── ...
└── features/  (computed later)
```

---

## Implementation

### Parallel Ingest Script

```python
# scripts/ingest_fills.py
import boto3
import lz4.frame
import polars as pl
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import json
from datetime import datetime, timedelta

s3 = boto3.client('s3', region_name='us-east-1')
SOURCE_BUCKET = 'hl-mainnet-node-data'
DEST_BUCKET = 'your-vigil-bucket'  # Update this
REQUEST_PAYER = {'RequestPayer': 'requester'}

def process_hour(date: str, hour: int) -> int:
    """Download, decompress, transform, upload one hour of fills."""
    key = f'node_fills_by_block/hourly/{date}/{hour}.lz4'

    # Stream download
    obj = s3.get_object(Bucket=SOURCE_BUCKET, Key=key, **REQUEST_PAYER)
    compressed = obj['Body'].read()

    # Decompress
    raw = lz4.frame.decompress(compressed)

    # Parse and flatten
    fills = []
    for line in raw.decode().strip().split('\n'):
        block = json.loads(line)
        for user, fill in block.get('events', []):
            fill['user'] = user
            fill['block_time'] = block['block_time']
            fills.append(fill)

    if not fills:
        return 0

    # Convert to Parquet
    df = pl.DataFrame(fills)
    parquet_buffer = BytesIO()
    df.write_parquet(parquet_buffer, compression='zstd')
    parquet_buffer.seek(0)

    # Upload to your S3
    dest_key = f'processed/fills/date={date[:4]}-{date[4:6]}-{date[6:]}/hour={hour:02d}.parquet'
    s3.put_object(Bucket=DEST_BUCKET, Key=dest_key, Body=parquet_buffer.getvalue())

    return len(fills)


def process_day(date: str, max_workers: int = 12) -> int:
    """Process all 24 hours in parallel."""
    total = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_hour, date, h): h for h in range(24)}
        for future in as_completed(futures):
            try:
                count = future.result()
                total += count
                print(f"  Hour {futures[future]:02d}: {count:,} fills")
            except Exception as e:
                print(f"  Hour {futures[future]:02d}: ERROR - {e}")
    return total


def process_date_range(start_date: str, end_date: str):
    """Process a range of dates."""
    start = datetime.strptime(start_date, '%Y%m%d')
    end = datetime.strptime(end_date, '%Y%m%d')
    current = start

    total_fills = 0
    while current <= end:
        date_str = current.strftime('%Y%m%d')
        print(f"Processing {date_str}...")
        count = process_day(date_str)
        total_fills += count
        print(f"  Day total: {count:,} fills\n")
        current += timedelta(days=1)

    print(f"Grand total: {total_fills:,} fills")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', required=True, help='Start date YYYYMMDD')
    parser.add_argument('--end', required=True, help='End date YYYYMMDD')
    args = parser.parse_args()

    process_date_range(args.start, args.end)
```

### Usage

```bash
# Single day
python scripts/ingest_fills.py --start 20251101 --end 20251101

# Full month
python scripts/ingest_fills.py --start 20251101 --end 20251130

# Full history
python scripts/ingest_fills.py --start 20250727 --end 20251130
```

---

## DB Loading from Parquet

Once data is in Parquet, loading into any database is fast:

### DuckDB (Recommended for Analysis)

```python
import duckdb

conn = duckdb.connect('vigil.db')
conn.execute("""
    INSTALL httpfs;
    LOAD httpfs;
    SET s3_region='us-east-1';
    SET s3_access_key_id='...';
    SET s3_secret_access_key='...';
""")

# Create table from all Parquet files
conn.execute("""
    CREATE TABLE fills AS
    SELECT * FROM read_parquet('s3://your-bucket/processed/fills/**/*.parquet')
""")

# Or query directly without loading
conn.execute("""
    SELECT user, coin, SUM(CAST(sz AS DOUBLE) * CAST(px AS DOUBLE)) as volume
    FROM read_parquet('s3://your-bucket/processed/fills/**/*.parquet')
    GROUP BY user, coin
    ORDER BY volume DESC
    LIMIT 100
""").fetchdf()
```

### TimescaleDB/Postgres

```sql
-- Using pg_parquet extension
COPY fills FROM 's3://bucket/fills/*.parquet' WITH (FORMAT parquet);

-- Or via Python with psycopg2 + pyarrow
```

### ClickHouse

```sql
INSERT INTO fills
SELECT * FROM s3(
    's3://your-bucket/processed/fills/**/*.parquet',
    'AWS_ACCESS_KEY', 'AWS_SECRET_KEY',
    'Parquet'
);
```

---

## Cost Estimate

| Approach | Transfer Cost | Compute Cost | Time |
|----------|---------------|--------------|------|
| Local Mac | ~$7 egress | $0 | 8-12 hrs |
| **EC2 us-east-1** | **$0** | **~$1.50** | **1-2 hrs** |
| AWS DataSync | $0.94 | $0 | 2-3 hrs |

### Recommended EC2 Setup

- **Instance:** c5.4xlarge ($0.68/hr) - 16 vCPU, 32 GB RAM
- **Region:** us-east-1 (same as source bucket)
- **Runtime:** ~2 hours for full history
- **Total cost:** ~$1.50

---

## Execution Plan

1. **Create S3 bucket** in us-east-1
2. **Launch EC2** (c5.4xlarge) in us-east-1
3. **Install dependencies:** `pip install boto3 lz4 polars`
4. **Run ingest script** for full date range
5. **Verify data** in S3
6. **Terminate EC2**
7. **Query with DuckDB** or load into database

---

## Schema Reference

### Input (JSON from Hyperliquid)

```json
{
  "user": "0x...",
  "coin": "BTC",
  "px": "95000.5",
  "sz": "0.1",
  "side": "B",
  "time": 1735689600000,
  "dir": "Open Long",
  "startPosition": "0.0",
  "closedPnl": "1234.56",
  "fee": "2.50",
  "crossed": true,
  "tid": 12345678,
  "oid": 87654321,
  "hash": "0x...",
  "block_time": "2025-11-01T12:00:00.123Z"
}
```

### Output (Parquet columns)

| Column | Type | Description |
|--------|------|-------------|
| user | string | Wallet address |
| coin | string | Asset symbol |
| px | string | Execution price |
| sz | string | Size |
| side | string | B=Buy, A=Sell |
| time | int64 | Unix timestamp (ms) |
| dir | string | Open/Close Long/Short |
| startPosition | string | Position before fill |
| closedPnl | string | Realized PnL |
| fee | string | Fee paid |
| crossed | bool | true=Taker |
| tid | int64 | Trade ID |
| oid | int64 | Order ID |
| hash | string | Transaction hash |
| block_time | string | Block timestamp |
| feeToken | string | Fee denomination |
| twapId | int64 | TWAP order ID (nullable) |
| builderFee | string | Builder fee (nullable) |
