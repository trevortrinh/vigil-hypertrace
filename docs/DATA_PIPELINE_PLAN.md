# Vigil: Data Pipeline Plan

## Goal

Build a trader intelligence system that:
1. Ingests Hyperliquid fill data from their public S3
2. Stores as Parquet in our S3 (data lake layer)
3. Loads into TimescaleDB (query layer)
4. Computes trader features and clusters traders into archetypes
5. Enables deep analysis to learn from successful traders

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                            us-east-2                                    │
│                                                                         │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐            │
│  │ Hyperliquid │─────▶│  Your S3    │─────▶│ TimescaleDB │            │
│  │ S3 (source) │      │  (Parquet)  │      │   (EC2)     │            │
│  └─────────────┘      └─────────────┘      └─────────────┘            │
│        │                    │                     │                    │
│   requester-pays       Data Lake              Query DB                 │
│   FREE in-region      (source of truth)      (fast queries)           │
│                       (backup/replay)        (aggregates)             │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
                                                    │
                                              Port 5432
                                                    │
                                    ┌───────────────┴───────────────┐
                                    │         Your Laptop           │
                                    │   - Jupyter notebooks         │
                                    │   - Connect to remote DB      │
                                    └───────────────────────────────┘
```

---

## Why This Architecture?

### 1. Parquet in S3 = Data Lake (Source of Truth)

| Benefit | Description |
|---------|-------------|
| **Immutable backup** | If DB corrupts, reload from Parquet |
| **Schema flexibility** | Can reload with different schema anytime |
| **Portability** | Works with Spark, Athena, DuckDB, etc. |
| **Cost effective** | S3 storage is cheap (~$0.023/GB/month) |
| **Decoupled** | DB can be rebuilt from scratch |

### 2. TimescaleDB = Query Layer (Fast Analysis)

| Benefit | Description |
|---------|-------------|
| **Indexes** | Fast lookups by user, coin, time |
| **Continuous aggregates** | Auto-updating daily trader stats |
| **SQL power** | Window functions, CTEs, complex joins |
| **Time-series optimized** | Hypertables, chunking, compression |

### 3. Same Region (us-east-2) = Free Transfer

Hyperliquid S3 is in `us-east-2`. Running EC2 in same region:

| Transfer Type | Cost for 75GB |
|--------------|---------------|
| Cross-region (to your laptop) | **$6.75** |
| Same-region (EC2 in us-east-2) | **$0.00** |

---

## Data Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  1. FETCH       │────▶│  2. TRANSFORM   │────▶│  3. LOAD        │
│                 │     │                 │     │                 │
│  Download .lz4  │     │  Decompress     │     │  Insert into    │
│  from HL S3     │     │  Parse JSON     │     │  TimescaleDB    │
│                 │     │  Write Parquet  │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │  Your S3        │
                        │  (Parquet)      │
                        │  Source of Truth│
                        └─────────────────┘
```

**Scripts:**
```bash
# 1. Fetch from Hyperliquid S3 → Your S3 as Parquet
python scripts/fetch_data.py --date 2025-11-01

# 2. Load from Parquet → TimescaleDB
python scripts/load_to_db.py --date 2025-11-01

# 3. Compute trader features
python scripts/compute_features.py --date 2025-11-01
```

---

## Iterative Approach

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Stage 1        │────▶│  Stage 2        │────▶│  Stage 3        │
│  1 Day Local    │     │  1 Month Cloud  │     │  Full History   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
     ~4.5M fills            ~135M fills            ~550M fills
     ~33K traders           ~100K traders          ~100K+ traders
     Docker locally         EC2 us-east-2          EC2 us-east-2
     ~15 min                ~3-4 hrs               ~10-12 hrs
```

---

## Stage 1: Local Development (1 Day)

**Purpose:** Validate the entire pipeline before scaling up.

### Setup

```
Your Laptop
├── Docker TimescaleDB (localhost:5432)
├── Local Parquet files (./data/)
├── Python scripts
└── Jupyter notebooks
```

### Data Volume

| Metric | Value |
|--------|-------|
| Date | November 1, 2025 |
| Fills | 4,470,719 |
| Unique traders | 33,654 |
| Volume | $3.1B |
| Compressed size (.lz4) | ~400 MB |
| Parquet size | ~500 MB |
| TimescaleDB size | ~2-3 GB |
| Processing time | ~15-20 min |

### Commands

```bash
# Start local TimescaleDB
docker-compose up -d

# Fetch 1 day → local Parquet
python scripts/fetch_data.py --date 2025-11-01 --output ./data/

# Load into local TimescaleDB
python scripts/load_to_db.py --source ./data/ --date 2025-11-01

# Run notebooks
jupyter notebook
```

### What You Validate

- [x] ETL pipeline works end-to-end
- [x] Parquet schema is correct
- [x] TimescaleDB schema and indexes work
- [x] Feature engineering queries run
- [x] Clustering produces meaningful results

---

## Stage 2: Cloud Scale-Up (1 Month)

**Purpose:** Full month of data for robust clustering and Sharpe ratios.

### Setup

```
EC2 (us-east-2)
├── TimescaleDB (Docker or installed)
├── S3 bucket (Parquet files)
└── Open port 5432 to your IP

Your Laptop
├── Connect to remote TimescaleDB
└── Run notebooks locally
```

### Data Volume

| Metric | Value |
|--------|-------|
| Date Range | November 1-30, 2025 |
| Fills | ~135M |
| Unique traders | ~100K |
| Compressed size (.lz4) | ~15 GB |
| Parquet size | ~20-30 GB |
| TimescaleDB size | ~50-80 GB |
| Processing time | ~3-4 hrs |

### EC2 Recommendation

| Component | Spec | Cost |
|-----------|------|------|
| Instance | r6g.large (2 vCPU, 16GB RAM) | ~$0.10/hr |
| Storage | 200GB gp3 EBS | ~$16/mo |
| Region | us-east-2 (same as Hyperliquid) | Free transfer |

### Commands

```bash
# SSH to EC2
ssh -i your-key.pem ec2-user@your-ec2-ip

# Fetch full month → S3 Parquet
python scripts/fetch_data.py \
  --start 2025-11-01 \
  --end 2025-11-30 \
  --output s3://your-bucket/parquet/

# Load into TimescaleDB
python scripts/load_to_db.py \
  --source s3://your-bucket/parquet/ \
  --start 2025-11-01 \
  --end 2025-11-30

# From your laptop: connect to remote DB
psql postgresql://user:pass@your-ec2-ip:5432/vigil
```

---

## Stage 3: Full History (Production)

**Purpose:** Complete trader profiles with 5 months of history.

### Data Volume

| Metric | Value |
|--------|-------|
| Date Range | July 27 - November 30, 2025 |
| Days | ~126 |
| Fills | ~550M |
| Compressed size (.lz4) | ~75 GB |
| Parquet size | ~100-150 GB |
| TimescaleDB size | ~250-300 GB |
| Processing time | ~10-12 hrs |

### EC2 Recommendation

| Component | Spec | Cost |
|-----------|------|------|
| Instance | r6g.xlarge (4 vCPU, 32GB RAM) | ~$0.20/hr |
| Storage | 500GB gp3 EBS | ~$40/mo |
| Region | us-east-2 | Free transfer |

---

## S3 Bucket Structure

```
s3://your-vigil-bucket/
├── raw/                              # Optional: keep original .lz4 files
│   └── node_fills_by_block/
│       ├── 20251101/
│       │   ├── 0.lz4
│       │   ├── 1.lz4
│       │   └── ...
│       └── ...
│
├── parquet/                          # Transformed data (source of truth)
│   └── fills/
│       ├── date=2025-11-01/
│       │   └── part-0000.parquet
│       ├── date=2025-11-02/
│       │   └── part-0000.parquet
│       └── ...
│
├── features/                         # Computed trader features
│   ├── trader_features_daily/
│   │   ├── date=2025-11-01/
│   │   └── ...
│   └── trader_features_monthly/
│       └── month=2025-11/
│
└── outputs/                          # Analysis outputs
    ├── clusters.parquet
    ├── trader_profiles.parquet
    └── cluster_summary.json
```

---

## TimescaleDB Schema

```sql
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Main fills table (hypertable)
CREATE TABLE fills (
    time TIMESTAMPTZ NOT NULL,
    user_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    price NUMERIC(20,8) NOT NULL,
    size NUMERIC(20,8) NOT NULL,
    side CHAR(1) NOT NULL,              -- 'B' or 'A'
    direction TEXT,                      -- 'Open Long', 'Close Short', etc.
    start_position NUMERIC(20,8),
    closed_pnl NUMERIC(20,8),
    fee NUMERIC(20,8),
    crossed BOOLEAN,                     -- true=taker, false=maker
    tx_hash TEXT,
    order_id BIGINT,
    trade_id BIGINT,
    block_time TIMESTAMPTZ
);

-- Convert to hypertable (auto-partitioned by time)
SELECT create_hypertable('fills', 'time', chunk_time_interval => INTERVAL '1 day');

-- Indexes for common queries
CREATE INDEX idx_fills_user_time ON fills (user_address, time DESC);
CREATE INDEX idx_fills_coin_time ON fills (coin, time DESC);
CREATE INDEX idx_fills_trade_id ON fills (trade_id);

-- Continuous aggregate: daily trader stats (auto-updates)
CREATE MATERIALIZED VIEW trader_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS day,
    user_address,
    COUNT(*) AS fill_count,
    SUM(price * size) AS volume,
    SUM(closed_pnl) AS realized_pnl,
    SUM(fee) AS fees_paid,
    SUM(CASE WHEN NOT crossed THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) AS maker_pct,
    SUM(CASE WHEN closed_pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
    SUM(CASE WHEN closed_pnl < 0 THEN 1 ELSE 0 END) AS losing_trades,
    COUNT(DISTINCT coin) AS unique_coins
FROM fills
GROUP BY day, user_address
WITH NO DATA;

-- Refresh policy (runs automatically every hour)
SELECT add_continuous_aggregate_policy('trader_daily',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

-- Trader profiles table (computed by script)
CREATE TABLE trader_profiles (
    user_address TEXT PRIMARY KEY,

    -- Activity
    first_trade TIMESTAMPTZ,
    last_trade TIMESTAMPTZ,
    active_days INT,
    total_volume NUMERIC(20,2),
    total_trades INT,
    unique_coins INT,

    -- Performance
    realized_pnl NUMERIC(20,2),
    fees_paid NUMERIC(20,2),
    net_pnl NUMERIC(20,2),
    pnl_per_trade NUMERIC(20,4),
    win_rate NUMERIC(5,4),
    profit_factor NUMERIC(10,4),

    -- Behavior
    maker_pct NUMERIC(5,4),
    avg_hold_time_minutes NUMERIC(10,2),
    avg_trade_size NUMERIC(20,2),
    long_short_ratio NUMERIC(10,4),

    -- Risk metrics
    sharpe_ratio NUMERIC(10,4),
    max_drawdown NUMERIC(20,2),
    consistency NUMERIC(10,4),          -- std dev of daily PnL

    -- Classification
    cluster_id INT,
    cluster_name TEXT,

    -- Metadata
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_profiles_cluster ON trader_profiles (cluster_id);
CREATE INDEX idx_profiles_pnl ON trader_profiles (net_pnl DESC);
```

---

## Parquet Schema

```python
# Schema for fills Parquet files
import pyarrow as pa

FILLS_SCHEMA = pa.schema([
    ('time', pa.timestamp('us', tz='UTC')),
    ('user_address', pa.string()),
    ('coin', pa.string()),
    ('price', pa.float64()),
    ('size', pa.float64()),
    ('side', pa.string()),              # 'B' or 'A'
    ('direction', pa.string()),         # 'Open Long', etc.
    ('start_position', pa.string()),    # Keep as string (can be large)
    ('closed_pnl', pa.float64()),
    ('fee', pa.float64()),
    ('crossed', pa.bool_()),
    ('tx_hash', pa.string()),
    ('order_id', pa.int64()),
    ('trade_id', pa.int64()),
    ('block_time', pa.timestamp('us', tz='UTC')),
])
```

---

## Cost Breakdown

### One-Time Costs (Loading Full Dataset)

| Item | Cost |
|------|------|
| S3 GET requests (75GB from HL) | ~$0.50 |
| S3 PUT requests (150GB Parquet) | ~$0.75 |
| EC2 r6g.xlarge for 12 hrs | ~$2.40 |
| **Total** | **~$4** |

### Monthly Costs (If Running 24/7)

| Item | Cost |
|------|------|
| S3 storage (150GB Parquet) | ~$3.50 |
| EC2 r6g.large 24/7 | ~$75 |
| EBS 500GB gp3 | ~$40 |
| **Total** | **~$120/mo** |

### Work Trial Strategy (Cheapest)

| Approach | Cost |
|----------|------|
| Run EC2 for 3 days, then shut down | ~$7 |
| Keep S3 Parquet (can reload anytime) | ~$3.50/mo |
| Re-launch EC2 when needed | Pay per use |
| **Total for work trial** | **~$10** |

---

## Trader Features

### Computed from Fills

**Activity Features:**
```python
volume              # SUM(price * size)
trade_count         # COUNT(*)
unique_coins        # COUNT(DISTINCT coin)
avg_trade_size      # AVG(price * size)
max_trade_size      # MAX(price * size)
active_days         # COUNT(DISTINCT DATE(time))
trades_per_day      # trade_count / active_days
```

**Performance Features:**
```python
realized_pnl        # SUM(closed_pnl)
fees_paid           # SUM(fee)
net_pnl             # realized_pnl - fees_paid
pnl_per_trade       # AVG(closed_pnl) WHERE closed_pnl != 0
win_rate            # SUM(closed_pnl > 0) / SUM(closed_pnl != 0)
profit_factor       # SUM(closed_pnl WHERE > 0) / ABS(SUM(closed_pnl WHERE < 0))
```

**Behavior Features:**
```python
maker_pct           # SUM(NOT crossed) / COUNT(*)
avg_hold_time       # AVG(close_time - open_time) per position
long_short_ratio    # Long volume / Short volume
loss_cut_speed      # AVG hold time on losing trades
winner_hold_time    # AVG hold time on winning trades
```

**Risk Features (need multiple days):**
```python
sharpe_ratio        # AVG(daily_pnl) / STDDEV(daily_pnl) * SQRT(365)
sortino_ratio       # Like Sharpe but only downside volatility
max_drawdown        # Largest peak-to-trough decline
consistency         # STDDEV(daily_pnl) - lower is more consistent
```

---

## Clustering Approach

### Algorithm Pipeline

```
1. Feature Matrix    →  2. Normalize      →  3. PCA           →  4. K-Means
   (30+ features)        (StandardScaler)    (reduce to 10-15)   (k=5-7)
                                                                      │
                                                                      ▼
5. UMAP Visualization  ←  6. Profile Clusters  ←  7. Validate
   (2D projection)         (describe each)         (silhouette score)
```

### Expected Clusters

| Cluster | Name | Key Traits |
|---------|------|------------|
| 0 | **HFT / Market Makers** | 80%+ maker, <5min holds, high volume, low edge/trade |
| 1 | **Smart Directional** | 30% maker, 1-8hr holds, high PnL, good Sharpe |
| 2 | **Scalpers** | Mixed maker/taker, 15-60min holds, high frequency |
| 3 | **Swing Traders** | Hours-to-days holds, lower frequency, larger size |
| 4 | **Retail Losers** | Low maker%, erratic sizing, negative PnL |
| 5 | **Degen Gamblers** | Very low maker%, random entries, large losses |

### Cluster Validation

- **Silhouette score:** Measure cluster separation (>0.3 is good)
- **Stability:** Do clusters hold across different time periods?
- **Predictive power:** Does cluster predict future PnL?

---

## Project Structure

```
vigil-contract/
├── src/vigil/
│   ├── __init__.py
│   ├── config.py           # Settings, AWS credentials, DB config
│   ├── s3.py               # S3 client (list, download, upload)
│   ├── etl.py              # Decompress LZ4, parse JSON, transform
│   ├── db.py               # TimescaleDB connection, batch inserts
│   ├── features.py         # Compute trader features
│   └── clustering.py       # K-Means, UMAP, cluster profiling
│
├── scripts/
│   ├── fetch_data.py       # CLI: HL S3 → Your S3 (Parquet)
│   ├── load_to_db.py       # CLI: Parquet → TimescaleDB
│   └── compute_features.py # CLI: Generate trader features
│
├── notebooks/
│   ├── 01_explore_data.ipynb        # (existing) Data exploration
│   ├── 02_analysis_pipeline.ipynb   # (existing) Basic analysis
│   ├── 03_feature_engineering.ipynb # Compute all trader features
│   ├── 04_clustering.ipynb          # K-Means, evaluation
│   ├── 05_visualization.ipynb       # UMAP, cluster profiles
│   └── 06_deep_dive.ipynb           # Study specific traders
│
├── sql/
│   ├── 001_schema.sql      # Tables, hypertables
│   ├── 002_indexes.sql     # Optimized indexes
│   └── 003_aggregates.sql  # Continuous aggregates
│
├── docker-compose.yml      # Local TimescaleDB
├── pyproject.toml          # Dependencies
│
└── docs/
    ├── VISION.md
    ├── ARCHITECTURE.md
    ├── DATA_PIPELINE_PLAN.md   # This document
    └── vigil-project-plan.md
```

---

## Dependencies

```toml
# pyproject.toml
[project]
dependencies = [
    # Existing
    "boto3>=1.35.0",
    "lz4>=4.0.0",
    "pandas>=2.0.0",
    "python-dotenv>=1.0.0",
    "tqdm>=4.66.0",

    # Data processing
    "polars>=0.20.0",         # Faster than pandas for large data
    "pyarrow>=14.0.0",        # Parquet support
    "duckdb>=0.9.0",          # SQL on Parquet (optional)

    # Database
    "psycopg[binary]>=3.1.0", # PostgreSQL driver
    "sqlalchemy>=2.0.0",      # ORM (optional)

    # Data science
    "scikit-learn>=1.3.0",    # Clustering, PCA
    "umap-learn>=0.5.0",      # UMAP visualization

    # Visualization
    "plotly>=5.18.0",         # Interactive plots
    "seaborn>=0.13.0",        # Statistical viz
    "matplotlib>=3.8.0",      # Basic plots
]
```

---

## Environment Variables

```bash
# .env
# AWS credentials
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-2

# Your S3 bucket
VIGIL_S3_BUCKET=your-vigil-bucket

# TimescaleDB (local)
DATABASE_URL=postgresql://postgres:password@localhost:5432/vigil

# TimescaleDB (EC2 - when deployed)
# DATABASE_URL=postgresql://postgres:password@your-ec2-ip:5432/vigil
```

---

## Docker Compose (Local Development)

```yaml
# docker-compose.yml
version: '3.8'

services:
  timescaledb:
    image: timescale/timescaledb:latest-pg16
    container_name: vigil-timescaledb
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
      POSTGRES_DB: vigil
    ports:
      - "5432:5432"
    volumes:
      - timescale_data:/var/lib/postgresql/data
      - ./sql:/docker-entrypoint-initdb.d  # Auto-run schema on first start
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  timescale_data:
```

---

## Timeline

| Day | Task | Deliverable |
|-----|------|-------------|
| **Day 1 AM** | Set up Docker + schema | TimescaleDB running locally |
| **Day 1 PM** | Build fetch script | Can download from HL S3 |
| **Day 1 PM** | Fetch Nov 1 data | 1 day of Parquet locally |
| **Day 2 AM** | Build load script | Can load Parquet → DB |
| **Day 2 AM** | Load Nov 1 | Data queryable in TimescaleDB |
| **Day 2 PM** | Feature engineering notebook | 30+ features per trader |
| **Day 3 AM** | Clustering notebook | 5-7 clusters identified |
| **Day 3 PM** | Visualization + profiles | UMAP plot, cluster descriptions |
| **Day 4** | Scale to EC2 + full month | Production-ready system |

---

## Success Criteria

### Technical
- [ ] Pipeline runs end-to-end (HL S3 → Parquet → TimescaleDB)
- [ ] Same code works for 1 day, 1 month, or full history
- [ ] Parquet files are properly partitioned by date
- [ ] TimescaleDB queries are fast (<1s for trader lookups)
- [ ] Continuous aggregates auto-update

### Analysis
- [ ] Features computed for all traders with >10 trades
- [ ] 5-7 distinct clusters with clear profiles
- [ ] "Smart" cluster identified with positive expected value
- [ ] Cluster predicts future performance (validation)

### Work Trial
- [ ] Clean, well-documented code
- [ ] Architecture decisions explained
- [ ] Impressive visualization (UMAP with clusters)
- [ ] Real insights extracted from data

---

## Next Steps

1. **Create S3 bucket** in us-east-2
2. **Set up local Docker** with TimescaleDB
3. **Build fetch_data.py** script
4. **Build load_to_db.py** script
5. **Fetch + load Nov 1** (proof of concept)
6. **Feature engineering notebook**
7. **Clustering notebook**
8. **Scale to EC2 for full month**
