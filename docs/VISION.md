# Vigil: Hyperliquid Trader Intelligence Engine

## The Vision

**One sentence**: Know what the best traders on Hyperliquid are doing before the market does.

**The machine**:
- Ingests every fill on Hyperliquid (~100K+ daily)
- Profiles 100K+ traders by performance and behavior
- Classifies them: HFT, Smart Directional, Basis, Retail
- Generates real-time signals when smart money moves

---

## Why This Works

### The Data Is Ready

```
s3://hl-mainnet-node-data/node_fills_by_block/hourly/
├── Jul 27, 2025 → Present (~5 months)
└── Every fill with: user, coin, price, size, PnL, fees, direction
```

**No reconstruction needed.** The hard work is done. Each fill contains:

| Field | What It Tells Us |
|-------|------------------|
| `user` | Wallet address |
| `coin` | What they traded |
| `px`, `sz` | Position size and entry |
| `dir` | Open Long/Short, Close Long/Short |
| `closedPnl` | Realized profit/loss |
| `fee` | Fees paid |
| `crossed` | Taker (true) or Maker (false) |
| `startPosition` | Position before this fill |

From this, we compute **everything**.

---

## The Pipeline

```
┌─────────────────┐
│  S3 Fills       │  ~5 months of complete data
│  (200-400 GB)   │  Every fill, every trader
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  PostgreSQL     │  Indexed by user, coin, time
│  + TimescaleDB  │  Partitioned by date
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌───────────────┐
│Daily  │ │Position       │
│Aggs   │ │Reconstruction │
└───┬───┘ └───────┬───────┘
    │             │
    └──────┬──────┘
           ▼
    ┌─────────────┐
    │  Trader     │  PnL, ROI, Sharpe, Win Rate
    │  Profiles   │  Maker%, Holding Period, Turnover
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │  Classify   │  HFT / Smart / Basis / Retail
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐
    │  Asset      │  Smart money L/S ratio
    │  Signals    │  Confluence alerts
    └─────────────┘
```

---

## Trader Metrics

### Tier 1: Direct From Fills
| Metric | Formula |
|--------|---------|
| Realized PnL | `SUM(closedPnl)` |
| Volume | `SUM(px * sz)` |
| Trade Count | `COUNT(*)` |
| Maker % | `SUM(crossed=false) / COUNT(*)` |
| Win Rate | `SUM(closedPnl > 0) / SUM(closedPnl != 0)` |
| Fees | `SUM(fee)` |
| Coins Traded | `COUNT(DISTINCT coin)` |

### Tier 2: From Position Reconstruction
| Metric | Approach |
|--------|----------|
| Avg Holding Period | Track Open→Close duration |
| MTM/TV | `PnL / Volume` (filters market makers) |
| Turnover | `Volume / Avg Position Size` |
| Long/Short Ratio | Net exposure over time |

### Tier 3: Performance
| Metric | Formula |
|--------|---------|
| ROI | `PnL / Peak Equity` |
| Sharpe | `Mean(Daily PnL) / StdDev(Daily PnL) * √365` |
| Max Drawdown | Largest peak-to-trough decline |

---

## Trader Classification

```python
def classify(trader):
    # HFT: High frequency, low edge per trade, mostly maker
    if (trader.maker_pct >= 0.70 and
        trader.turnover >= 5.0 and
        trader.mtm_tv <= 0.0010 and  # ≤10 bps
        trader.avg_hold_hours <= 1.0):
        return "HFT"

    # Smart Directional: High PnL, good Sharpe, holds positions
    if (trader.all_time_pnl >= 500_000 and
        trader.mtm_tv >= 0.0010 and  # ≥10 bps
        trader.avg_hold_hours >= 1.0 and
        trader.sharpe >= 1.5):
        return "SMART_DIRECTIONAL"

    # Basis: Long holds, low turnover (likely hedged elsewhere)
    if (trader.avg_hold_hours >= 24 and
        trader.turnover <= 0.5):
        return "LIKELY_BASIS"

    return "RETAIL"
```

---

## Asset Signals

Once traders are classified, aggregate their activity:

```sql
-- Smart money positioning by coin (hourly)
SELECT
    coin,
    SUM(CASE WHEN direction LIKE 'Open Long%' THEN notional ELSE 0 END) as smart_long,
    SUM(CASE WHEN direction LIKE 'Open Short%' THEN notional ELSE 0 END) as smart_short,
    smart_long / NULLIF(smart_short, 0) as ls_ratio,
    COUNT(DISTINCT user) as smart_trader_count
FROM fills f
JOIN trader_profiles t ON f.user = t.address
WHERE t.trader_type = 'SMART_DIRECTIONAL'
  AND f.time >= NOW() - INTERVAL '1 hour'
GROUP BY coin;
```

### Signal Types

| Signal | Trigger | Action |
|--------|---------|--------|
| Smart Money Confluence | Z-score > 1.5, L/S ratio > 2x | Alert: "18 smart traders long BTC" |
| Fresh Wallet Accumulation | Volume from wallets < 7d old > 2x avg | Alert: "Fresh wallet activity on DOGE" |
| Whale Position | Smart trader opens > $1M position | Alert: "0xdef opened $2.1M BTC long" |

---

## Implementation Plan

### Week 1: Data Pipeline
- [ ] Download `node_fills_by_block` (Jul 2025 → now)
- [ ] Parse LZ4/JSON, load into PostgreSQL
- [ ] Build incremental sync for new data
- [ ] Validate sample wallets against HypurrScan

### Week 2: Metrics & Profiles
- [ ] Compute daily aggregates per trader
- [ ] Implement position reconstruction (holding periods)
- [ ] Build trader profiles table
- [ ] Validate against Hyperliquid leaderboard

### Week 3: Classification & Signals
- [ ] Implement classification heuristics
- [ ] Build asset signals aggregation
- [ ] Create alerts table
- [ ] API endpoints for querying

### Week 4: Real-time
- [ ] Connect to Hyperliquid WebSocket
- [ ] Stream new fills
- [ ] Update metrics in real-time
- [ ] Push alerts (Telegram/webhook)

---

## What We Skip

| Approach | Why Skip |
|----------|----------|
| Matching engine reconstruction | Data already has fills |
| API backfill | Convenient data is complete |
| Historical data (pre-Jul 2025) | Not needed for current analysis |
| Order book replay | Fills are sufficient |

---

## Success Metrics

| Milestone | Validation |
|-----------|------------|
| Data loaded | Row counts match S3 file counts |
| Trader PnL correct | Top 10 match Hyperliquid leaderboard |
| Classification working | HFTs have expected characteristics |
| Signals firing | Backtested confluence predicts moves |

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Storage | PostgreSQL + TimescaleDB |
| ETL | Python (boto3, pandas, lz4) |
| API | FastAPI |
| Real-time | Hyperliquid WebSocket + Redis |
| Alerts | Telegram Bot |

---

## Data Volume

| Metric | Estimate |
|--------|----------|
| Fill records | ~50-100M (5 months) |
| Unique traders | ~100K |
| Daily new fills | ~100-200K |
| Storage (raw) | ~200-400 GB compressed |
| Storage (DB) | ~500 GB - 1 TB |

---

## The Edge

**What we see that others don't:**

1. **Every fill, every trader** - Not just leaderboard, everyone
2. **Real-time classification** - Know who's smart before they're famous
3. **Confluence detection** - When smart money aligns, we know first
4. **Fresh wallet tracking** - Catch new alpha before it's priced in

**The output**: Actionable signals embedded in G3 Terminal.
