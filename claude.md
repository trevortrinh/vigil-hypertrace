# Vigil - Hyperliquid Trader Intelligence Engine

A data pipeline and analytics system that identifies and classifies traders on Hyperliquid based on their trading performance and behavior patterns.

## Tech Stack

- **Language**: Python 3.12+
- **Package Manager**: uv
- **Database**: TimescaleDB (cloud via TigerDB)
- **Data Processing**: Polars, PyArrow, Pandas
- **Storage**: AWS S3 (parquet), Hyperliquid S3 (source)
- **Task Runner**: just (justfile)

## Project Structure

```
src/vigil/           # Core library
  config.py          # Environment config (AWS, DB, paths)
  s3.py              # S3 client with requester-pays support
  transforms.py      # LZ4/JSON/msgpack parsing, Parquet I/O
  db.py              # Database connection and COPY loading

scripts/             # CLI entry points
  fetch_data.py           # Download fills from Hyperliquid S3 → Parquet
  cloud_load.py           # Load Parquet files → TimescaleDB (parallel)
  find_new_smart_money.py # Find traders who started after a cutoff date
  deploy_lambda.py        # Deploy HTTP proxy Lambda for IP rotation

lambda/              # AWS Lambda functions
  http_proxy/
    handler.py       # HTTP proxy for IP rotation on rate-limited APIs

sql/                 # Database schema (run in order)
  001_fills.sql           # Fills hypertable (partitioned by time)
  002_load_tracking.sql   # Track loaded parquet files (resumable)
  003_continuous_aggregates.sql  # trader_daily, coin_daily, builder_daily + trader_profiles

notebooks/           # Jupyter analysis notebooks
docs/                # Architecture, vision, research documentation
data/                # Local data storage (gitignored)
```

## Commands

```bash
# Setup
uv sync                    # Install dependencies

# Data pipeline
just fetch-data            # Download from Hyperliquid S3 → parquet
just cloud-load            # Load parquet → database (parallel)

# Database
just db-query "SQL"        # Run SQL query
just db-base               # Run base migrations (001 + 002)
just db-aggregates         # Create continuous aggregates (003)
just db-refresh            # Refresh all aggregates + trader_profiles
just db-reset              # Drop schema + recreate + run base
just db-shell              # Interactive psql

# Utilities
just clean                 # Clear local data
just disk                  # Show data directory size
```

## Environment Variables

Required in `.env` (see `.env.example`):

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` - S3 access
- `DATABASE_URL` - PostgreSQL connection string
- `PARQUET_S3` - S3 path for parquet storage (e.g., `s3://bucket/path/`)

## Data Flow

```
Hyperliquid S3 (hl-mainnet-node-data/)
    ↓ fetch_data.py (LZ4 decompress, JSON parse)
Parquet files (S3)
    ↓ cloud_load.py (parallel COPY)
TimescaleDB fills hypertable
    ↓ Continuous aggregates (auto-refresh)
trader_daily, coin_daily, builder_daily
    ↓ Materialized view
trader_profiles (with classification)
```

## SQL Pipeline Architecture

All analytics are pure SQL - no Python needed for metrics.

### Layer 1: Continuous Aggregates (auto-refresh)
- `trader_daily` - Per-trader daily stats (fills, volume, PnL, fees, maker%, win rate)
- `coin_daily` - Per-coin daily stats
- `builder_daily` - Per-builder/frontend daily stats

### Layer 2: Trader Profiles (materialized view)
- Aggregates trader_daily → lifetime metrics
- Computes Sharpe ratio in SQL: `AVG(pnl) / STDDEV(pnl) * √365`
- Classifies traders via CASE statement

### Layer 3: Convenience Views
- `top_traders_by_type` - Aggregate metrics by classification
- `smart_money_positions` - Recent SMART_DIRECTIONAL activity
- `recent_liquidations` - Parsed liquidation events

## Trader Classification

```sql
CASE
    WHEN liquidation_pct >= 0.20 THEN 'LIQUIDATOR'
    WHEN maker_pct >= 0.70 AND ABS(mtm_tv) <= 0.001 THEN 'HFT'
    WHEN net_pnl >= 100000 AND mtm_tv >= 0.001 AND sharpe >= 1.0 THEN 'SMART_DIRECTIONAL'
    ELSE 'RETAIL'
END
```

| Type | Criteria |
|------|----------|
| LIQUIDATOR | ≥20% of fills are liquidations |
| HFT | ≥70% maker, ≤10bps edge per trade |
| SMART_DIRECTIONAL | ≥$100K PnL, ≥10bps edge, ≥1.0 Sharpe |
| RETAIL | Everyone else |

## Key Conventions

- **Column names**: Hyperliquid uses camelCase, database uses snake_case (auto-converted in db.py)
- **Dual storage**: Code handles both local filesystem and S3 paths transparently
- **Incremental loading**: `load_progress` table tracks loaded files, scripts skip already-processed files
- **Time column**: `time` is in milliseconds (Unix epoch)
- **Numeric precision**: Values stored as TEXT in parquet, converted on load

## EC2 Deployment

For loading large datasets, run from EC2 in us-east-1 (same region as Hyperliquid S3):

```bash
# Copy repo to EC2
rsync -avz --exclude='.venv' --exclude='data' --exclude='.git' \
  -e "ssh -i ~/.ssh/key.pem" . ec2-user@<ip>:~/vigil/

# On EC2
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
nohup uv run python -u scripts/cloud_load.py > load.log 2>&1 &
tail -f load.log
```

## Lambda IP Rotation

For querying the Hyperliquid API at scale (thousands of traders), rate limits become a bottleneck. The Lambda proxy provides IP rotation by leveraging AWS Lambda's ephemeral execution environment.

### How It Works

```
find_new_smart_money.py
    ↓ boto3.invoke()
vigil-http-proxy Lambda (us-east-1)
    ↓ urllib.request
Hyperliquid API
```

Each Lambda invocation gets a different IP from AWS's pool, effectively bypassing per-IP rate limits.

### Deployment

```bash
# Deploy Lambda function + IAM role
python scripts/deploy_lambda.py

# Test deployment
python scripts/deploy_lambda.py --test

# Delete Lambda + role
python scripts/deploy_lambda.py --delete
```

### Find New Smart Money

Identifies traders from `smart_money_watchlist` who started trading after a cutoff date (default: Aug 1, 2025). Useful for finding fresh alpha - traders who achieved smart money status quickly.

```bash
# Basic usage (top 50 traders, direct requests)
uv run python scripts/find_new_smart_money.py

# Check all smart money traders
uv run python scripts/find_new_smart_money.py --all

# Use Lambda for IP rotation (faster, no rate limits)
uv run python scripts/find_new_smart_money.py --all --lambda

# Lambda with 10 concurrent workers
uv run python scripts/find_new_smart_money.py --all --lambda -w 10

# Custom cutoff date
uv run python scripts/find_new_smart_money.py --cutoff 2025-10-01
```

Output is streamed to JSONL (`data/new_smart_money_YYYYMMDD.jsonl`):
```json
{"user_address": "0x...", "is_new": true, "first_fill": "2025-09-15", "last_fill": "2025-12-01", "api_closed_pnl": 150000.00, "db_net_pnl": 148500.00, "sharpe_ratio": 2.15, ...}
```

### Lambda Metadata Logging

When using `--lambda`, request metadata is logged to `data/lambda_YYYYMMDD_HHMMSS.jsonl`:
- Request timing and duration
- Lambda internal IP (for debugging IP rotation)
- Unique IPs used across all requests

## Current Focus

- Data ingestion pipeline is operational
- Pure SQL trader classification implemented
- Trader classification logic documented in `docs/VISION.md`
- Analysis notebooks for exploratory work
