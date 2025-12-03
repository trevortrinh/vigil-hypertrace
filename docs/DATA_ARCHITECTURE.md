# Data Architecture Guide

Understanding views, materialized views, continuous aggregates, and the Vigil data pipeline.

---

## View vs Materialized View vs Table

| Type | Data Stored? | When Computed | Use Case |
|------|--------------|---------------|----------|
| **View** | No | Every query (live) | Simple, always fresh, but slow on big data |
| **Materialized View** | Yes | On REFRESH command | Pre-computed, fast reads, manual refresh |
| **Continuous Aggregate** | Yes | Automatically | TimescaleDB special - auto-refreshes as data arrives |
| **Table** | Yes | On INSERT | Full control, you manage updates |

### View

```sql
CREATE VIEW trader_daily AS
SELECT user_address, SUM(volume) ...
FROM fills
GROUP BY user_address;
```

- No data stored
- Query re-runs the full aggregation every time
- Always up-to-date
- **Problem**: Slow on millions of rows

### Materialized View

```sql
CREATE MATERIALIZED VIEW trader_daily_mv AS
SELECT user_address, SUM(volume) ...
FROM fills
GROUP BY user_address;

-- Must manually refresh
REFRESH MATERIALIZED VIEW trader_daily_mv;
```

- Data IS stored (like a table)
- Fast reads (pre-computed)
- Must manually refresh to update
- Stale until refreshed

### Continuous Aggregate (TimescaleDB)

```sql
CREATE MATERIALIZED VIEW trader_daily_cagg
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(86400000, time) AS day,
    user_address,
    SUM(volume) ...
FROM fills
GROUP BY day, user_address;

-- Auto-refresh policy
SELECT add_continuous_aggregate_policy('trader_daily_cagg',
    start_offset => NULL,
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);
```

- Data stored AND automatically updated
- Refreshes incrementally (only new data)
- Can include real-time recent data
- **Best of both worlds for time-series**

---

## Current Schema

```sql
-- 001_fills.sql
fills (hypertable)        -- Raw data, partitioned by time

-- 002_transformations.sql
trader_daily (VIEW)       -- Re-computes on EVERY query (slow)
trader_profiles (TABLE)   -- Empty, waiting for analysis pipeline
```

### The Problem

`trader_daily` is a **view**, so every query scans the entire `fills` table and re-aggregates. With millions of fills, this gets slow.

---

## Recommended Architecture

```
                        +-------------------------------------+
                        |           fills (hypertable)        |
                        |         ~100M+ rows, raw data       |
                        +-----------------+-------------------+
                                          |
              +---------------------------+---------------------------+
              |                           |                           |
              v                           v                           v
+-------------------------+  +---------------------+  +---------------------+
|  trader_daily_cagg      |  |  coin_daily_cagg    |  |  Python Pipeline    |
|  (continuous aggregate) |  |  (continuous agg)   |  |                     |
|                         |  |                     |  |  - Position recon   |
|  Pre-aggregated daily   |  |  Volume/OI by coin  |  |  - Holding periods  |
|  stats per trader       |  |  per day            |  |  - Sharpe calc      |
+-----------+-------------+  +-----------+---------+  +-----------+---------+
            |                            |                        |
            +----------------------------+------------------------+
                                         |
                                         v
                        +-------------------------------------+
                        |       trader_profiles (table)       |
                        |                                     |
                        |  Final metrics, classification      |
                        |  Updated by analysis pipeline       |
                        +-------------------------------------+
                                         |
                                         v
                        +-------------------------------------+
                        |       asset_signals (table)         |
                        |                                     |
                        |  Smart money positioning by coin    |
                        +-------------------------------------+
```

---

## SQL vs Python: When to Use Each

| Computation | SQL? | Python? | Why |
|-------------|------|---------|-----|
| SUM, COUNT, AVG per trader | Yes | Avoid | SQL is faster for aggregations |
| Daily rollups | Yes | Avoid | Use continuous aggregates |
| Win rate (closes with PnL > 0) | Yes | Yes | Simple filter + count |
| **Position reconstruction** | No | Yes | Requires row-by-row state tracking |
| **Holding periods** | No | Yes | Depends on position reconstruction |
| **Sharpe ratio** | Maybe | Yes | Needs daily PnL series, std dev |
| Classification | No | Yes | Business logic with thresholds |

### Key Insight

SQL is great for **aggregations** (GROUP BY, SUM, COUNT).

Python is required for **stateful computations** where you need to track state across rows (like position reconstruction).

---

## Continuous Aggregate Schema

Replace the slow view with a continuous aggregate:

```sql
-- Drop the slow view
DROP VIEW IF EXISTS trader_daily;

-- Create continuous aggregate
CREATE MATERIALIZED VIEW trader_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(86400000::bigint, time) AS day,
    user_address,
    COUNT(*) AS fill_count,
    SUM((px::numeric) * (sz::numeric)) AS volume,
    SUM(COALESCE(closed_pnl::numeric, 0)) AS realized_pnl,
    SUM(COALESCE(fee::numeric, 0)) AS fees_paid,
    AVG(CASE WHEN NOT crossed THEN 1.0 ELSE 0.0 END) AS maker_pct,
    SUM(CASE WHEN closed_pnl::numeric > 0 THEN 1 ELSE 0 END) AS winning_trades,
    SUM(CASE WHEN closed_pnl::numeric < 0 THEN 1 ELSE 0 END) AS losing_trades,
    COUNT(DISTINCT coin) AS unique_coins
FROM fills
GROUP BY day, user_address
WITH NO DATA;

-- Auto-refresh policy (hourly, materializes up to 1 hour ago)
SELECT add_continuous_aggregate_policy('trader_daily',
    start_offset => NULL,
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- Initial population (backfill all historical data)
CALL refresh_continuous_aggregate('trader_daily', NULL, NULL);
```

### Refresh Policy Explained

```sql
add_continuous_aggregate_policy('trader_daily',
    start_offset => NULL,           -- From the beginning of time
    end_offset => INTERVAL '1 hour', -- Materialize up to 1 hour ago
    schedule_interval => INTERVAL '1 hour'  -- Run every hour
);
```

- `start_offset => NULL`: Include all historical data
- `end_offset => '1 hour'`: Don't materialize the last hour (allows for late-arriving data)
- `schedule_interval => '1 hour'`: Run the refresh job every hour

### Real-Time Mode (Optional)

To include the most recent (non-materialized) data in queries:

```sql
ALTER MATERIALIZED VIEW trader_daily SET (timescaledb.materialized_only = false);
```

This makes queries combine:
1. Materialized data (fast, from disk)
2. Real-time data (slower, computed on-the-fly for recent rows)

---

## Coin-Level Continuous Aggregate

For asset signals, create a coin-level aggregate:

```sql
CREATE MATERIALIZED VIEW coin_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(86400000::bigint, time) AS day,
    coin,
    COUNT(*) AS fill_count,
    COUNT(DISTINCT user_address) AS unique_traders,
    SUM((px::numeric) * (sz::numeric)) AS volume,
    SUM(CASE WHEN dir LIKE 'Open Long%' OR dir LIKE 'Close Short%' THEN (sz::numeric) ELSE 0 END) AS buy_volume,
    SUM(CASE WHEN dir LIKE 'Open Short%' OR dir LIKE 'Close Long%' THEN (sz::numeric) ELSE 0 END) AS sell_volume
FROM fills
GROUP BY day, coin
WITH NO DATA;

SELECT add_continuous_aggregate_policy('coin_daily',
    start_offset => NULL,
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);
```

---

## Data Pipeline Summary

### What Lives Where

| Data | Storage Type | Updated By |
|------|--------------|------------|
| Raw fills | `fills` hypertable | `load_to_db.py` (from S3/local parquet) |
| Daily trader stats | `trader_daily` continuous aggregate | TimescaleDB (automatic) |
| Daily coin stats | `coin_daily` continuous aggregate | TimescaleDB (automatic) |
| Trader profiles | `trader_profiles` table | Python analysis pipeline |
| Asset signals | `asset_signals` table | Python analysis pipeline |

### Pipeline Flow

```
1. Data Ingestion
   S3 parquet files --> load_to_db.py --> fills table

2. Automatic Aggregation (TimescaleDB handles this)
   fills --> trader_daily (continuous aggregate)
   fills --> coin_daily (continuous aggregate)

3. Analysis Pipeline (Python)
   - Read from trader_daily for basic stats
   - Read from fills for position reconstruction
   - Compute: holding periods, Sharpe, classification
   - Write to trader_profiles

4. Signal Generation (Python)
   - Read from coin_daily + trader_profiles
   - Identify smart money activity
   - Write to asset_signals
```

---

## Quick Reference

| Question | Answer |
|----------|--------|
| Do I need more tables? | Convert view to continuous aggregate, keep existing tables |
| What's a materialized view? | Pre-computed query results stored on disk |
| What's a continuous aggregate? | Materialized view that auto-refreshes (TimescaleDB) |
| When to use Python vs SQL? | SQL for aggregations, Python for stateful logic |
| How often does data refresh? | Configure with `add_continuous_aggregate_policy` |
