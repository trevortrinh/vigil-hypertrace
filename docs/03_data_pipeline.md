# Trader Intelligence Pipeline

Pure SQL analytics - everything computed in TimescaleDB.

## Architecture

```
fills (hypertable, 960M rows)
    │
    │ continuous aggregate (auto-refresh hourly)
    ▼
trader_daily ──────────────────────────────┐
    │ - daily PnL, volume, maker%          │
    │ - liquidation/TWAP activity          │
    │                                      │
    │ materialized view (refresh on demand)│
    ▼                                      │
trader_profiles ◄──────────────────────────┘
    │ - lifetime stats
    │ - Sharpe = AVG(pnl) / STDDEV(pnl) * √365
    │ - Classification = CASE statement
    │
    ▼
API / Dashboard
```

**No Python in the core pipeline.** Everything is SQL.

## Quick Start

```bash
# Local
just db-local-up && just db-local-migrate
just cloud-sample && just local-load
just db-local-refresh && just db-local-stats

# Cloud
just db-migrate && just cloud-load
just db-refresh && just db-stats
```

## Data Flow

| Layer | What | Refresh |
|-------|------|---------|
| `fills` | Raw data (append-only) | On insert |
| `trader_daily` | Daily stats per trader | Auto (hourly) |
| `coin_daily` | Daily stats per coin | Auto (hourly) |
| `builder_daily` | Daily stats per frontend | Auto (hourly) |
| `trader_profiles` | Lifetime stats + classification | On demand |

## Schema

### Level 1: Continuous Aggregates

These auto-refresh. New fills → new aggregated rows.

**`trader_daily`**
```sql
SELECT
    day, user_address,
    fill_count, volume, realized_pnl, fees_paid,
    maker_fills, taker_fills,
    winning_fills, losing_fills,
    liquidation_fills, twap_fills,
    ...
FROM trader_daily;
```

**`coin_daily`**
```sql
SELECT
    day, coin,
    fill_count, unique_traders, volume,
    buy_volume, sell_volume,
    liquidation_count, liquidation_volume,
    ...
FROM coin_daily;
```

### Level 2: Materialized View

Aggregates trader_daily → lifetime metrics + Sharpe + classification.

**`trader_profiles`**
```sql
SELECT
    user_address,
    trading_days, total_fills, total_volume,
    net_pnl, maker_pct, win_rate, mtm_tv,
    sharpe_ratio,  -- computed in SQL!
    trader_type,   -- classified in SQL!
    ...
FROM trader_profiles;
```

### Convenience Views

Live queries, no refresh needed.

**`top_traders_by_type`** - Summary by classification
**`smart_money_positions`** - Hourly L/S by smart traders
**`recent_liquidations`** - Parsed liquidation events

## Computed Metrics (All SQL)

| Metric | Formula |
|--------|---------|
| `maker_pct` | `maker_fills / total_fills` |
| `win_rate` | `winning_fills / closing_fills` |
| `mtm_tv` | `realized_pnl / volume` |
| `sharpe_ratio` | `AVG(daily_pnl) / STDDEV(daily_pnl) * √365` |
| `trader_type` | CASE statement on metrics |

## Classification Logic

```sql
CASE
    WHEN liquidation_pct >= 0.20 THEN 'LIQUIDATOR'
    WHEN maker_pct >= 0.70 AND ABS(mtm_tv) <= 0.001 THEN 'HFT'
    WHEN net_pnl >= 100000 AND mtm_tv >= 0.001 AND sharpe_ratio >= 1.0 THEN 'SMART_DIRECTIONAL'
    ELSE 'RETAIL'
END
```

| Type | Criteria |
|------|----------|
| LIQUIDATOR | ≥20% of fills are liquidations |
| HFT | ≥70% maker, ≤10bps edge |
| SMART_DIRECTIONAL | ≥$100K PnL, ≥10bps edge, ≥1.0 Sharpe |
| RETAIL | Everyone else |

## Commands

```bash
# Refresh everything
just db-refresh

# View stats
just db-stats

# Query directly
just db-query "SELECT * FROM trader_profiles WHERE trader_type = 'SMART_DIRECTIONAL' ORDER BY net_pnl DESC LIMIT 20"

# View liquidations
just db-query "SELECT * FROM recent_liquidations LIMIT 50"

# Smart money by coin
just db-query "SELECT * FROM smart_money_positions WHERE coin = 'BTC' ORDER BY hour DESC LIMIT 24"
```

## Live Data Integration

When live WebSocket data arrives:

1. Insert into `fills` table
2. `trader_daily` auto-updates (continuous aggregate)
3. Call `REFRESH MATERIALIZED VIEW trader_profiles` periodically

That's it. No Python processing needed.

## Python Usage

Python is only for:

- **Notebooks**: Exploratory analysis
- **API**: Serving data (FastAPI)
- **Scripts**: Data loading, migrations
- **Future ML**: Clustering beyond simple heuristics

Not for:
- Aggregations
- Metrics computation
- Classification

## Files

```
sql/
├── 001_fills.sql              # Base hypertable
├── 002_load_tracking.sql      # Load state tracking
└── 003_continuous_aggregates.sql  # The pipeline

scripts/
├── fetch_data.py              # S3 → parquet
├── cloud_sample.py            # cloud DB → parquet
├── cloud_load.py              # parquet → cloud DB
└── local_load.py              # parquet → local DB
```
