# Vigil: Cloud Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                    AWS                                           │
│                                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐ │
│  │ Hyperliquid  │     │  Your S3     │     │ TimescaleDB  │     │  FastAPI   │ │
│  │ S3 (source)  │────▶│  (raw data)  │────▶│  (RDS)       │────▶│  (ECS)     │ │
│  └──────────────┘     └──────────────┘     └──────────────┘     └─────┬──────┘ │
│         │                    │                    │                    │        │
│         │              EventBridge          Aggregation            Dashboard    │
│         │              (hourly)             Jobs (ECS)             (Amplify)    │
│         │                                                                       │
└─────────│───────────────────────────────────────────────────────────────────────┘
          │
          │ --request-payer requester
          │
    ┌─────┴─────┐
    │ HL S3     │
    │ (public)  │
    └───────────┘
```

---

## Components

### 1. Data Ingestion (Lambda + EventBridge)

**Job**: Hourly sync of new fills from Hyperliquid S3

```python
# Runs every hour via EventBridge
def sync_new_fills():
    # 1. List new files in HL S3
    # 2. Copy to our S3 (backup)
    # 3. Parse and insert into TimescaleDB
```

**Why Lambda?**
- Cheap for hourly jobs
- No infrastructure to manage
- Can scale for backfill

**Alternative**: ECS Fargate task (if processing is heavy)

---

### 2. Raw Data Lake (S3)

```
s3://vigil-data-{account-id}/
├── raw/
│   └── node_fills_by_block/
│       ├── 20250727/00/*.lz4
│       └── ...
├── processed/
│   └── fills/
│       └── parquet files (optional)
└── exports/
    └── trader_profiles.csv
```

**Why keep raw?**
- Replay if DB corrupts
- Reprocess with new logic
- Audit trail

---

### 3. TimescaleDB (RDS PostgreSQL)

**Why TimescaleDB?**
- Time-series optimized (fills are time-series)
- Automatic partitioning (hypertables)
- Continuous aggregates (pre-computed rollups)
- It's just PostgreSQL (familiar, robust)

**Instance**: `db.r6g.large` to start (~$150/mo)
- 2 vCPU, 16 GB RAM
- 500 GB gp3 storage

**Schema**:
```sql
-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Raw fills (hypertable, partitioned by time)
CREATE TABLE fills (
    time TIMESTAMPTZ NOT NULL,
    user_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    price NUMERIC(20,8) NOT NULL,
    size NUMERIC(20,8) NOT NULL,
    side CHAR(1) NOT NULL,
    direction TEXT NOT NULL,
    closed_pnl NUMERIC(20,8),
    fee NUMERIC(20,8),
    crossed BOOLEAN,
    start_position NUMERIC(20,8),
    tx_hash TEXT,
    order_id BIGINT,
    trade_id BIGINT
);

SELECT create_hypertable('fills', 'time');

-- Indexes
CREATE INDEX idx_fills_user ON fills (user_address, time DESC);
CREATE INDEX idx_fills_coin ON fills (coin, time DESC);

-- Continuous aggregate: daily trader stats
CREATE MATERIALIZED VIEW trader_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS day,
    user_address,
    SUM(price * size) AS volume,
    COUNT(*) AS trade_count,
    SUM(closed_pnl) AS realized_pnl,
    SUM(fee) AS fees,
    SUM(CASE WHEN NOT crossed THEN 1 ELSE 0 END)::FLOAT / COUNT(*) AS maker_pct,
    SUM(CASE WHEN closed_pnl > 0 THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN closed_pnl < 0 THEN 1 ELSE 0 END) AS losses
FROM fills
GROUP BY day, user_address;

-- Refresh policy (runs automatically)
SELECT add_continuous_aggregate_policy('trader_daily',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
```

---

### 4. Processing Layer (ECS Fargate)

**Jobs**:

| Job | Frequency | Purpose |
|-----|-----------|---------|
| `sync-fills` | Hourly | Pull new fills from HL S3 |
| `compute-profiles` | Daily | Refresh trader_profiles table |
| `classify-traders` | Daily | Update trader classifications |
| `compute-signals` | Hourly | Generate asset signals |

**Why ECS Fargate?**
- No servers to manage
- Pay per use
- Can run longer jobs than Lambda (15 min limit)

---

### 5. API (FastAPI on ECS)

```python
# Endpoints
GET /traders/{address}          # Trader profile
GET /traders?type=SMART&limit=100  # List by classification
GET /traders/{address}/fills    # Recent fills
GET /assets/{coin}/signals      # Asset signals
GET /alerts                     # Recent alerts
GET /leaderboard               # Top traders by PnL
```

**Deployment**: ECS Fargate with ALB
**Cost**: ~$30-50/mo for small service

---

### 6. Dashboard (Next.js on Amplify)

**Pages**:
- `/` - Overview: top signals, market summary
- `/traders` - Searchable trader list with filters
- `/traders/{address}` - Deep dive on single trader
- `/assets/{coin}` - Asset-level signals
- `/alerts` - Alert feed

**Why Amplify?**
- Easy deploy from git
- Free tier generous
- Built-in auth if needed

---

## Cost Estimate (Monthly)

| Component | Spec | Cost |
|-----------|------|------|
| TimescaleDB (RDS) | db.r6g.large, 500GB | ~$150 |
| S3 Storage | 500 GB | ~$12 |
| S3 Transfer (initial) | 400 GB one-time | ~$36 |
| ECS Fargate | 2 vCPU, 4GB, 10 hrs/day | ~$50 |
| Lambda | Hourly syncs | ~$5 |
| ALB | API load balancer | ~$20 |
| Amplify | Dashboard hosting | Free tier |
| **Total** | | **~$270/mo** |

**Initial backfill** (one-time): ~$36 for 400GB transfer

---

## Implementation Order

### Phase 1: Infrastructure (Day 1-2)
```bash
# Terraform or CDK
- VPC with private subnets
- RDS PostgreSQL + TimescaleDB
- S3 bucket
- IAM roles
```

### Phase 2: Data Pipeline (Day 3-5)
```python
# scripts/
├── sync_fills.py      # Hourly job: HL S3 → our S3 → DB
├── backfill.py        # One-time: load all historical data
└── parse_fills.py     # LZ4 decompression + JSON parsing
```

### Phase 3: Metrics (Day 6-8)
```sql
-- Continuous aggregates + materialized views
-- trader_daily, trader_profiles, asset_signals
```

### Phase 4: API (Day 9-10)
```python
# api/
├── main.py
├── routes/
│   ├── traders.py
│   ├── assets.py
│   └── alerts.py
└── models/
```

### Phase 5: Dashboard (Day 11-14)
```typescript
// Next.js app
├── pages/
│   ├── index.tsx
│   ├── traders/
│   └── assets/
└── components/
```

---

## Alternative: Cheaper Stack

If cost is a concern:

| Component | Cheaper Option | Cost |
|-----------|---------------|------|
| TimescaleDB | Self-managed on EC2 t3.large | ~$60/mo |
| ECS | Lambda only | ~$10/mo |
| Dashboard | Grafana (free) | $0 |
| **Total** | | **~$100/mo** |

Trade-off: More ops work, less polished dashboard.

---

## Alternative: ClickHouse Instead of TimescaleDB

For pure analytics (no OLTP needs):

**Pros**:
- 10-100x faster aggregations
- Better compression
- Great for dashboards

**Cons**:
- Less familiar (not PostgreSQL)
- Weaker ecosystem
- Updates are harder

**When to use**: If query speed on large aggregations matters more than flexibility.

---

## Local Dev Setup

```bash
# Run TimescaleDB locally
docker run -d --name timescaledb \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=password \
  timescale/timescaledb:latest-pg15

# Sync sample data
python scripts/sync_fills.py --days 7 --local

# Run API
uvicorn api.main:app --reload

# Run dashboard
cd dashboard && npm run dev
```

---

## Repo Structure

```
vigil-contract/
├── infra/                    # Terraform/CDK
│   ├── main.tf
│   ├── rds.tf
│   ├── s3.tf
│   └── ecs.tf
├── scripts/
│   ├── sync_fills.py         # Hourly sync job
│   ├── backfill.py           # Initial data load
│   ├── compute_profiles.py   # Daily job
│   └── classify.py           # Classification logic
├── api/
│   ├── main.py
│   ├── routes/
│   ├── models/
│   └── db.py
├── dashboard/
│   ├── pages/
│   ├── components/
│   └── package.json
├── sql/
│   ├── schema.sql
│   ├── continuous_aggs.sql
│   └── views.sql
└── tests/
```

---

## Next Steps

1. **Set up AWS infra** (VPC, RDS, S3)
2. **Write sync script** (pull from HL S3)
3. **Backfill data** (Jul 2025 → now)
4. **Build aggregations** (continuous aggregates)
5. **API + Dashboard**

Want me to start with the infrastructure (Terraform) or the sync script (Python)?
