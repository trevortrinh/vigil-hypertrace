# Vigil Data Pipeline Setup

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         EC2                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ fetch_data  │───▶│  Parquet    │───▶│ load_to_db  │     │
│  │   (cron)    │    │   (temp)    │    │   (cron)    │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│        │                   │                   │            │
└────────┼───────────────────┼───────────────────┼────────────┘
         │                   │                   │
         ▼                   ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│  Hyperliquid   │  │    Your S3     │  │      RDS       │
│  S3 (source)   │  │   (parquet)    │  │  TimescaleDB   │
└────────────────┘  └────────────────┘  └────────────────┘
                            │                   │
                            ▼                   ▼
                    ┌────────────────────────────────┐
                    │         Local Dev              │
                    │  • aws s3 sync (subset)        │
                    │  • Docker TimescaleDB          │
                    │  • Notebooks                   │
                    └────────────────────────────────┘
```

**Data Flow:**
1. Run `fetch_data.py` → pulls ALL available data from Hyperliquid S3, saves Parquet to your S3
2. Run `load_to_db.py` → reads from your S3, loads to RDS TimescaleDB
3. Local dev syncs subset of Parquet from S3, runs against local Docker TimescaleDB
4. Re-run fetch periodically to get new data (skips existing files)

## Project Structure

```
vigil-contract/
├── src/vigil/                 # Shared library code
│   ├── __init__.py
│   ├── config.py              # Settings (env-aware)
│   ├── s3.py                  # S3 client, download helpers
│   ├── transforms.py          # Parse fills, schema helpers
│   └── db.py                  # DB connection, COPY helpers
├── scripts/
│   ├── fetch_data.py          # CLI: S3 → Parquet (uses src/vigil/)
│   └── load_to_db.py          # CLI: Parquet → DB (uses src/vigil/)
├── notebooks/                 # Import from src/vigil/
├── sql/                       # Schema definitions
├── docker-compose.yml         # Local TimescaleDB
├── pyproject.toml             # Package config
└── justfile                   # Local + deploy commands
```

## Local Dev Workflow

```bash
# Start local DB
just db-up

# Fetch data locally (for testing)
python scripts/fetch_data.py --date 2025-11-29

# Or sync subset from S3 (after EC2 is running)
aws s3 sync s3://your-bucket/vigil/parquet/20251129/ ./data/parquet/20251129/

# Load to local DB
python scripts/load_to_db.py

# Explore in notebooks
jupyter lab
```

## EC2 Production Setup

### 1. RDS TimescaleDB

```bash
# Create RDS instance
aws rds create-db-instance \
  --db-instance-identifier vigil-timescale \
  --db-instance-class db.t3.medium \
  --engine postgres \
  --engine-version 16 \
  --master-username postgres \
  --master-user-password <password> \
  --allocated-storage 100 \
  --vpc-security-group-ids sg-xxx

# After creation, enable TimescaleDB extension
psql -h vigil-timescale.xxx.us-east-2.rds.amazonaws.com -U postgres -d vigil
CREATE EXTENSION IF NOT EXISTS timescaledb;
\i sql/001_fills.sql
\i sql/002_transformations.sql
```

### 2. EC2 Instance

Small instance (t3.small) - just runs scripts, no DB.

```bash
# EC2 one-time setup
sudo yum install -y python3.12 git
pip install uv
git clone <repo>
cd vigil && uv sync
cp .env.example .env
# Edit .env with prod values
```

**IAM Role for EC2:**
- S3 read access to `hl-mainnet-node-data` (Hyperliquid)
- S3 read/write access to your bucket
- No AWS keys needed if using IAM role

### 3. Fetch All Data

The script lists all available dates/hours in the Hyperliquid bucket and fetches everything (skipping files that already exist in your S3).

```bash
ssh ec2-host
cd vigil

# Fetch ALL available data from Hyperliquid → your S3
python scripts/fetch_data.py --all --output s3://your-bucket/vigil/parquet/

# Load everything to RDS
python scripts/load_to_db.py --source s3://your-bucket/vigil/parquet/
```

To update with new data later, just re-run - it skips existing files:
```bash
python scripts/fetch_data.py --all --output s3://your-bucket/vigil/parquet/
python scripts/load_to_db.py --source s3://your-bucket/vigil/parquet/
```

## Environment Configuration

**.env.local** (your machine)
```
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
AWS_REGION=us-east-2
DATABASE_URL=postgresql://postgres:password@localhost:5435/vigil
DATA_DIR=./data
```

**.env.prod** (EC2 - or use IAM role, no keys needed)
```
DATABASE_URL=postgresql://postgres:xxx@vigil-timescale.xxx.rds.amazonaws.com:5432/vigil
OUTPUT_BUCKET=s3://your-bucket/vigil/parquet
AWS_REGION=us-east-2
```

## Summary

| Component | Local | Production |
|-----------|-------|------------|
| Compute | Your machine | EC2 (t3.small) |
| Database | Docker TimescaleDB | RDS TimescaleDB |
| Parquet | ./data/ | S3 bucket |
| Scheduling | Manual | Manual (re-run to update) |

## Cost Estimate

- EC2 t3.small: ~$15/month
- RDS t3.medium: ~$30/month
- S3: minimal (depends on data volume)
