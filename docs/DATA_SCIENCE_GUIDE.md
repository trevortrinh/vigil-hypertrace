# Data Science Guide for Vigil

A practical guide for mining Hyperliquid fills data to build trader intelligence.

## Goal

Turn raw fills into **trader intelligence**:
1. **Tier 1**: Direct aggregations (volume, PnL, fees, maker%)
2. **Tier 2**: Position reconstruction (holding periods, win rate)
3. **Tier 3**: Classification (HFT, Smart Directional, Basis)
4. **Tier 4**: Asset signals (smart money positioning)

---

## Tools

| Tool | Purpose |
|------|---------|
| **Polars** | Fast DataFrame operations (like pandas but faster) |
| **SQL** | Aggregations in TimescaleDB |
| **NumPy** | Numerical computations (Sharpe, etc.) |

### Polars vs SQL Decision

| Use SQL when... | Use Polars when... |
|-----------------|---------------------|
| Aggregating millions of rows | Manipulating intermediate results |
| Simple GROUP BY operations | Complex row-by-row logic |
| Data lives in DB | Position reconstruction |

---

## Tier 1: Direct Aggregations

Straightforward SQL queries on the `fills` table.

### Trader Lifetime Stats

```sql
SELECT
    user_address,
    COUNT(*) as total_trades,
    SUM(px::numeric * sz::numeric) as total_volume,
    SUM(COALESCE(closed_pnl::numeric, 0)) as realized_pnl,
    SUM(COALESCE(fee::numeric, 0)) as fees_paid,
    AVG(CASE WHEN NOT crossed THEN 1.0 ELSE 0.0 END) as maker_pct,
    COUNT(DISTINCT coin) as unique_coins,
    MIN(time) as first_trade,
    MAX(time) as last_trade
FROM fills
GROUP BY user_address;
```

### Daily Aggregation

```sql
SELECT
    user_address,
    (time / 86400000) * 86400000 as day_ms,  -- floor to day
    SUM(px::numeric * sz::numeric) as volume,
    SUM(COALESCE(closed_pnl::numeric, 0)) as pnl
FROM fills
GROUP BY user_address, day_ms;
```

---

## Tier 2: Position Reconstruction

The **key algorithm** for Vigil. Track positions to compute:
- Holding periods
- Win rate (per closed trade, not per fill)
- Long/short ratio

### The Algorithm (Polars)

```python
import polars as pl

def reconstruct_positions(fills_df: pl.DataFrame) -> pl.DataFrame:
    """
    Track open->close cycles for each (user, coin) pair.
    Returns completed trades with holding period and PnL.
    """
    # Sort by time
    fills = fills_df.sort("time")

    positions = {}  # (user, coin) -> {size, entry_time, entry_price}
    trades = []

    for row in fills.iter_rows(named=True):
        key = (row["user_address"], row["coin"])
        pos = positions.get(key, {"size": 0, "entry_time": None, "cost_basis": 0})

        sz = float(row["sz"])
        px = float(row["px"])
        direction = row["dir"]

        if direction and direction.startswith("Open"):
            # Adding to position
            if pos["size"] == 0:
                pos["entry_time"] = row["time"]
            pos["cost_basis"] += px * sz
            pos["size"] += sz

        elif direction and direction.startswith("Close"):
            # Closing position - record the trade
            if pos["entry_time"]:
                holding_ms = row["time"] - pos["entry_time"]
                trades.append({
                    "user_address": row["user_address"],
                    "coin": row["coin"],
                    "holding_period_ms": holding_ms,
                    "closed_pnl": float(row["closed_pnl"] or 0),
                    "exit_time": row["time"],
                })

            pos["size"] -= sz
            if pos["size"] <= 0:
                pos = {"size": 0, "entry_time": None, "cost_basis": 0}

        positions[key] = pos

    return pl.DataFrame(trades)
```

### Derived Metrics

```python
trades_df = reconstruct_positions(fills_df)

# Win rate (% of profitable trades)
win_rate = (trades_df["closed_pnl"] > 0).mean()

# Average holding period
avg_hold_hours = trades_df["holding_period_ms"].mean() / 3600000

# Profit factor (gross wins / gross losses)
wins = trades_df.filter(pl.col("closed_pnl") > 0)["closed_pnl"].sum()
losses = trades_df.filter(pl.col("closed_pnl") < 0)["closed_pnl"].abs().sum()
profit_factor = wins / losses if losses > 0 else float('inf')
```

---

## Key Metrics Formulas

### MTM/TV (Mark-to-Market / Trading Volume)

```python
mtm_tv = total_pnl / total_volume
# < 0.001 (10bps) = likely market maker
# > 0.001 = directional trader
```

### Sharpe Ratio

```python
import numpy as np

def sharpe_ratio(daily_pnl: np.array, risk_free: float = 0) -> float:
    """Annualized Sharpe ratio from daily PnL series."""
    excess_returns = daily_pnl - risk_free
    if excess_returns.std() == 0:
        return 0
    return (excess_returns.mean() / excess_returns.std()) * np.sqrt(365)

# Example
daily_pnl = np.array([100, -50, 200, 150, -75, 300])
print(sharpe_ratio(daily_pnl))  # ~2.5
```

### Turnover

```python
turnover = total_volume / avg_position_notional
# > 5x = high frequency
# < 1x = position holder
```

---

## Trader Classification

Decision tree based on behavioral metrics:

```python
def classify_trader(profile: dict) -> str:
    """
    Classify trader based on behavioral metrics.
    """
    # HFT: High maker%, high turnover, low MTM/TV, short holds
    if (profile["maker_pct"] >= 0.70 and
        profile["turnover"] >= 5.0 and
        profile["mtm_tv"] <= 0.001 and
        profile["avg_hold_hours"] <= 1.0):
        return "HFT"

    # Smart Directional: Profitable, reasonable hold times
    if (profile["mtm_tv"] >= 0.001 and
        profile["avg_hold_hours"] >= 1.0 and
        profile["realized_pnl"] >= 100_000 and
        profile["sharpe"] >= 1.0):
        return "SMART_DIRECTIONAL"

    # Basis: Long holds, capital efficient
    if (profile["avg_hold_hours"] >= 24 and
        profile["maker_pct"] >= 0.5):
        return "BASIS"

    return "RETAIL"
```

### Classification Criteria

| Type | Maker % | Turnover | MTM/TV | Hold Time | Other |
|------|---------|----------|--------|-----------|-------|
| **HFT** | >= 70% | >= 5x | <= 10bps | <= 1 hour | High volume |
| **Smart Directional** | Any | Any | >= 10bps | >= 1 hour | PnL >= $100k, Sharpe >= 1 |
| **Basis** | >= 50% | Low | Any | >= 24 hours | Static positions |
| **Retail** | Any | Any | Any | Any | Default |

---

## Workflow Pattern

### Step 1: SQL for Heavy Lifting

```sql
-- Get daily stats per trader (run in DB)
CREATE MATERIALIZED VIEW trader_daily_stats AS
SELECT
    user_address,
    (time / 86400000) as day,
    SUM(px::numeric * sz::numeric) as volume,
    SUM(COALESCE(closed_pnl::numeric, 0)) as pnl,
    COUNT(*) as trades,
    AVG(CASE WHEN NOT crossed THEN 1.0 ELSE 0.0 END) as maker_pct
FROM fills
GROUP BY user_address, day;
```

### Step 2: Pull into Polars for Analysis

```python
from vigil.db import execute_query

# Get top traders by volume
df = execute_query("""
    SELECT user_address, SUM(volume) as total_volume, SUM(pnl) as total_pnl
    FROM trader_daily_stats
    GROUP BY user_address
    ORDER BY total_volume DESC
    LIMIT 1000
""")
```

### Step 3: Compute Advanced Metrics in Python

```python
# For each top trader, compute Sharpe
for user in top_traders:
    daily_pnl = execute_query(f"""
        SELECT day, pnl FROM trader_daily_stats
        WHERE user_address = '{user}'
        ORDER BY day
    """)
    sharpe = sharpe_ratio(daily_pnl["pnl"].to_numpy())
```

### Step 4: Write Back to DB

```python
# Insert computed profiles into trader_profiles table
```

---

## Quick Reference

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **Win Rate** | profitable_closes / total_closes | >50% is good |
| **Profit Factor** | gross_wins / gross_losses | >1.5 is solid |
| **Sharpe** | mean(daily_pnl) / std(daily_pnl) * sqrt(365) | >2 is excellent |
| **MTM/TV** | total_pnl / total_volume | <10bps = market maker |
| **Maker %** | maker_fills / total_fills | >70% = likely MM |
| **Turnover** | volume / avg_position | >5x = HFT |

---

## Data Pipeline Summary

```
fills (hypertable)
    │
    ├──► SQL: trader_daily (view)
    │         │
    │         └──► Polars: Daily PnL series
    │                   │
    │                   └──► Sharpe, consistency
    │
    ├──► Polars: Position reconstruction
    │         │
    │         └──► Holding periods, win rate, profit factor
    │
    └──► SQL + Polars: Classification
              │
              └──► trader_profiles table
                        │
                        └──► Asset signals (aggregate by coin)
```

---

## Next Steps

1. **Run Tier 1** - Build the `trader_daily` view and basic profiles
2. **Implement position reconstruction** - The algorithm above
3. **Compute Sharpe** - Daily PnL series per trader
4. **Classify** - Apply heuristics
5. **Asset signals** - Aggregate by coin instead of user
