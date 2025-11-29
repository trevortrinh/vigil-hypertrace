# Vigil: Hyperliquid Trader Intelligence Engine

## Project Overview

Build a machine that continuously generates deep, actionable insights about Hyperliquid traders and assets.

**Core Outputs:**
1. Trader profiles with performance metrics (PnL, ROI, Sharpe, etc.)
2. Trader classification (HFT, Smart Directional, Basis)
3. Asset-level signals (smart money positioning, fresh wallet activity, confluence alerts)

---

## Data Architecture

### Primary Data Source: Hyperliquid S3

```
s3://hl-mainnet-node-data/
├── node_fills_by_block/hourly/  # Jul 27, 2025 → current (BEST)
├── node_fills/                   # May 25 - Jul 27, 2025
└── node_trades/                  # Mar 22 - May 25, 2025 (basic)
```

**Using post-May 2025 data as spec suggests.**

### Fill Record Schema (What We Get)

```json
{
  "user": "0x...",           // Wallet address
  "coin": "BTC",             // Asset
  "px": "95000.5",           // Execution price
  "sz": "0.1",               // Size
  "side": "B",               // Buy or Sell
  "time": 1735689600000,     // Unix ms
  "dir": "Open Long",        // Open Long/Short, Close Long/Short
  "startPosition": "0.0",    // Position before fill
  "closedPnl": "0",          // Realized PnL (on closes)
  "fee": "-0.95",            // Fee paid
  "feeToken": "USDC",
  "crossed": true,           // Taker (true) or Maker (false)
  "hash": "0x...",
  "oid": 123456,
  "tid": 789012,
  "builder_fee": "0.1"       // Builder fee (newer data)
}
```

---

## Metric Computation Matrix

### Tier 1: Direct from Fills (Straightforward)

| Metric | Formula | Fields Used |
|--------|---------|-------------|
| **Realized PnL** | `SUM(closedPnl)` | closedPnl |
| **Total Volume** | `SUM(px * sz)` | px, sz |
| **Trade Count** | `COUNT(*)` | - |
| **Maker %** | `COUNT(crossed=false) / COUNT(*)` | crossed |
| **Fees Paid** | `SUM(fee)` | fee |
| **Coins Traded** | `COUNT(DISTINCT coin)` | coin |
| **First Trade** | `MIN(time)` | time |
| **Last Trade** | `MAX(time)` | time |
| **Wallet Age** | `NOW() - MIN(time)` | time |

### Tier 2: Requires Position Reconstruction

| Metric | Approach | Complexity |
|--------|----------|------------|
| **Average Holding Period** | Track Open→Close pairs, compute duration | Medium |
| **Win Rate** | `closedPnl > 0` events / total closes | Easy |
| **Long/Short Ratio** | Track net position direction over time | Medium |
| **MTM/TV** | `Realized PnL / Volume` | Easy |
| **Turnover** | `Volume / Avg Notional Position` | Medium |

### Tier 3: Requires Position + External Data

| Metric | What's Needed | Source |
|--------|---------------|--------|
| **Unrealized PnL** | Current positions + mark prices | Hyperliquid API |
| **Funding PnL** | Position history + funding rates | API + S3 |
| **Average Leverage** | Position notional / margin | API (clearinghouseState) |
| **ROI** | PnL / Average Equity over time | Requires equity snapshots |
| **Sharpe** | Daily PnL series, std dev | Computed from Tier 2 |
| **Deposit Amount** | Bridge transfers | S3 asset_ctxs or API |

### Tier 4: Complex / Future

| Metric | Notes |
|--------|-------|
| **Aggressiveness** | Slippage vs mid price at fill time - needs L2 book data |
| **Regime-adjusted Sharpe** | Requires market regime classification first |

---

## Position Reconstruction Algorithm

To compute holding periods, unrealized PnL, and leverage, we need to reconstruct positions over time.

```python
# Pseudocode for position reconstruction
positions = {}  # {(wallet, coin): Position}

class Position:
    size: float = 0
    entry_price: float = 0
    entry_time: int = 0
    cost_basis: float = 0

for fill in fills.order_by('time'):
    key = (fill.user, fill.coin)
    pos = positions.get(key, Position())

    if fill.dir.startswith('Open'):
        # Adding to position
        new_size = pos.size + fill.sz
        pos.cost_basis += fill.px * fill.sz
        pos.entry_price = pos.cost_basis / new_size
        if pos.size == 0:
            pos.entry_time = fill.time
        pos.size = new_size

    elif fill.dir.startswith('Close'):
        # Reducing position
        holding_period = fill.time - pos.entry_time
        pos.size -= fill.sz
        if pos.size == 0:
            # Position fully closed
            record_trade(wallet, coin, holding_period, fill.closedPnl)
            pos = Position()  # Reset

    positions[key] = pos
```

---

## Database Schema

### Core Tables

```sql
-- Raw fills (partitioned by date)
CREATE TABLE fills (
    id BIGSERIAL PRIMARY KEY,
    user_address VARCHAR(42) NOT NULL,
    coin VARCHAR(20) NOT NULL,
    price DECIMAL(20,8) NOT NULL,
    size DECIMAL(20,8) NOT NULL,
    side CHAR(1) NOT NULL,  -- 'B' or 'S'
    direction VARCHAR(20) NOT NULL,  -- 'Open Long', 'Close Short', etc.
    start_position DECIMAL(20,8),
    closed_pnl DECIMAL(20,8),
    fee DECIMAL(20,8),
    fee_token VARCHAR(10),
    crossed BOOLEAN,  -- true = taker
    tx_hash VARCHAR(66),
    order_id BIGINT,
    trade_id BIGINT,
    block_number BIGINT,
    timestamp TIMESTAMPTZ NOT NULL,

    INDEX idx_user_time (user_address, timestamp),
    INDEX idx_coin_time (coin, timestamp),
    INDEX idx_timestamp (timestamp)
) PARTITION BY RANGE (timestamp);

-- Trader daily metrics (materialized)
CREATE TABLE trader_daily_metrics (
    user_address VARCHAR(42) NOT NULL,
    date DATE NOT NULL,

    -- Volume & Activity
    total_volume DECIMAL(20,2),
    trade_count INT,
    unique_coins INT,

    -- PnL
    realized_pnl DECIMAL(20,2),
    fees_paid DECIMAL(20,2),
    net_pnl DECIMAL(20,2),  -- realized_pnl - fees

    -- Behavior
    maker_count INT,
    taker_count INT,
    maker_pct DECIMAL(5,2),

    -- Wins/Losses
    winning_trades INT,
    losing_trades INT,
    win_rate DECIMAL(5,2),

    -- Position metrics
    avg_trade_size DECIMAL(20,2),
    max_position_notional DECIMAL(20,2),

    PRIMARY KEY (user_address, date)
);

-- Trader aggregate profile
CREATE TABLE trader_profiles (
    user_address VARCHAR(42) PRIMARY KEY,

    -- Lifetime metrics
    first_trade TIMESTAMPTZ,
    last_trade TIMESTAMPTZ,
    wallet_age_days INT,
    total_volume DECIMAL(20,2),
    total_trades INT,
    unique_coins INT,

    -- PnL
    all_time_pnl DECIMAL(20,2),
    pnl_30d DECIMAL(20,2),
    pnl_7d DECIMAL(20,2),

    -- Performance
    roi DECIMAL(10,4),
    sharpe DECIMAL(10,4),
    win_rate DECIMAL(5,2),

    -- Behavior
    maker_pct DECIMAL(5,2),
    avg_holding_period_hours DECIMAL(10,2),
    avg_leverage DECIMAL(5,2),
    mtm_tv DECIMAL(10,6),  -- PnL / Volume
    turnover DECIMAL(10,2),

    -- Classification
    trader_type VARCHAR(20),  -- 'HFT', 'SMART_DIRECTIONAL', 'BASIS', 'RETAIL', 'UNKNOWN'
    confidence_score DECIMAL(5,2),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Asset signals (aggregated from trader activity)
CREATE TABLE asset_signals (
    coin VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,

    -- Smart money positioning
    smart_money_long_notional DECIMAL(20,2),
    smart_money_short_notional DECIMAL(20,2),
    smart_money_ls_ratio DECIMAL(10,4),

    -- Activity
    smart_money_volume DECIMAL(20,2),
    fresh_wallet_volume DECIMAL(20,2),

    -- Confluence
    smart_trader_count_long INT,
    smart_trader_count_short INT,
    confluence_zscore DECIMAL(5,2),

    PRIMARY KEY (coin, timestamp)
);

-- Alerts
CREATE TABLE alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    coin VARCHAR(20),
    user_address VARCHAR(42),
    severity VARCHAR(10),  -- 'LOW', 'MEDIUM', 'HIGH'
    message TEXT,
    metadata JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    acknowledged BOOLEAN DEFAULT FALSE
);
```

---

## Trader Classification Heuristics

### HFT Detection
```python
def is_hft(trader):
    return (
        trader.maker_pct >= 0.70 and
        trader.turnover >= 5.0 and
        trader.mtm_tv <= 0.0010 and  # 10bps
        trader.avg_holding_period_hours <= 1.0 and
        trader.total_volume >= VOLUME_THRESHOLD  # TBD
    )
```

### Smart Directional Trader
```python
def is_smart_directional(trader):
    return (
        trader.mtm_tv >= 0.0010 and  # 10bps
        trader.avg_holding_period_hours >= 1.0 and
        trader.all_time_pnl >= 500_000 and
        trader.sharpe >= SHARPE_THRESHOLD  # TBD, maybe 1.0+
    )
```

### Basis Trader (Harder - usually hedged elsewhere)
```python
def is_likely_basis(trader):
    return (
        trader.avg_holding_period_hours >= 24 and  # Static positions
        trader.avg_leverage >= 3.0 and  # Capital efficient
        # Would need to check if positions tend to have positive funding
    )
```

---

## Implementation Phases

### Phase 1: Data Pipeline (Week 1)
- [ ] Pull all `node_fills_by_block` data from S3 (Jul 2025+)
- [ ] Pull `node_fills` data (May-Jul 2025)
- [ ] Parse LZ4 files, load into PostgreSQL
- [ ] Build incremental sync for new data
- [ ] Validate against HypurrScan / Leaderboard

**Deliverable:** Raw fills in DB, queryable by wallet/coin/time

### Phase 2: Tier 1 Metrics (Week 1-2)
- [ ] Compute daily aggregates per trader
- [ ] Build `trader_daily_metrics` materialized view
- [ ] Compute lifetime trader profiles
- [ ] Implement Tier 1 metrics (volume, PnL, maker%, win rate)

**Deliverable:** `trader_profiles` table with basic metrics

### Phase 3: Position Reconstruction (Week 2)
- [ ] Implement position tracking algorithm
- [ ] Compute holding periods per trade
- [ ] Calculate turnover, MTM/TV
- [ ] Validate against sample wallets on HypurrScan

**Deliverable:** Enhanced profiles with holding period, turnover

### Phase 4: Classification (Week 2-3)
- [ ] Implement HFT detection heuristics
- [ ] Implement Smart Directional detection
- [ ] Flag and tag traders
- [ ] Build confidence scores
- [ ] Validate against known traders

**Deliverable:** Classified trader profiles

### Phase 5: Asset Signals (Week 3)
- [ ] Aggregate smart money positioning by coin
- [ ] Compute L/S ratios
- [ ] Build fresh wallet tracking
- [ ] Implement confluence z-score
- [ ] Build alerting system

**Deliverable:** Asset signals table, alerts

### Phase 6: Real-time (Week 4+)
- [ ] Connect to Hyperliquid WebSocket/API
- [ ] Stream new fills
- [ ] Update metrics in real-time
- [ ] Push alerts

---

## Validation Strategy

### Compare Against Known Sources

| Source | What to Validate |
|--------|------------------|
| **Hyperliquid Leaderboard** | Top trader PnL rankings |
| **ASXN/Allium Dashboard** | PnL numbers, volume |
| **HypurrScan** | Individual wallet transactions |

### Sample Wallets

Pick 10-20 wallets spanning:
- Top PnL traders
- High-volume traders
- Known HFTs (if identifiable)
- Fresh wallets
- Random sample

Compare our computed metrics against what's shown on dashboards.

---

## Tech Stack Recommendation

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **Database** | PostgreSQL + TimescaleDB | Time-series optimized, good for aggregations |
| **ETL** | Python (boto3 + pandas) | S3 access, LZ4 decompression |
| **API** | FastAPI | Quick to build, async |
| **Real-time** | Hyperliquid WebSocket + Redis | Low-latency updates |
| **Alerts** | Telegram Bot / Webhook | Immediate notifications |

### Alternative: ClickHouse
If data volume is massive (billions of fills), ClickHouse would be better for analytics queries. PostgreSQL is fine for MVP.

---

## Open Questions

1. **Equity/Margin Data**: How do we get historical equity per wallet? Needed for ROI, Sharpe. Options:
   - Snapshot from API periodically
   - Infer from position sizes + prices
   - Use deposit data as proxy

2. **Funding Rates**: Need historical funding rate data per coin to compute Funding PnL. Is this in S3 or API only?

3. **Thresholds**: What constitutes "high volume"? What Sharpe threshold for "smart"? Need to explore data distribution first.

4. **Lighter Integration**: Spec mentions Lighter traders - is this a separate exchange? Need data source.

5. **HyperTrace**: Spec mentions this tool. Is it available? What does it provide beyond S3 fills?

---

## Next Steps

1. **Confirm data source**: S3 fills is sufficient for Phase 1-4?
2. **Set up infrastructure**: PostgreSQL instance, Python env
3. **Pull sample data**: Start with 1 week of fills to validate pipeline
4. **Build fill parser**: Handle LZ4, JSON lines format
5. **Compute sample metrics**: Validate against leaderboard

---

## Appendix: Metric Definitions

### MTM/TV (Mark-to-Market / Trading Volume)
```
MTM/TV = Total PnL / Total Volume
```
Low MTM/TV (< 10bps) indicates market makers who profit from spread, not direction.

### Turnover
```
Turnover = Trading Volume / Average Notional Position
```
High turnover (> 5x) indicates frequent position changes, typical of HFT.

### Sharpe Ratio
```
Sharpe = Mean(Daily Returns) / StdDev(Daily Returns) * sqrt(365)
```
Annualized risk-adjusted return. > 2.0 is excellent.

### Win Rate
```
Win Rate = Profitable Closes / Total Closes
```
Only counts closed positions with `closedPnl != 0`.
