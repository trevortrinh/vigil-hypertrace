# Vigil Trader Intelligence Analysis Guide

A comprehensive guide to understanding the trader analysis in `notebooks/db_analysis.ipynb`.

## Overview

The analysis pipeline transforms raw Hyperliquid fill data into actionable trader intelligence through:

1. **Data Aggregation** - SQL-based metrics computation
2. **Trader Classification** - Heuristic-based categorization
3. **Statistical Analysis** - Distribution and correlation analysis
4. **ML Clustering** - Unsupervised trader segmentation
5. **Signal Generation** - Identifying actionable patterns

---

## Data Flow

```
fills (raw trades)
    │
    ├──► trader_daily (continuous aggregate)
    │         │
    │         └──► Daily PnL, volume, maker %
    │
    ├──► trader_profiles (materialized view)
    │         │
    │         └──► Lifetime stats, Sharpe, classification
    │
    └──► Analysis Notebook
              │
              ├──► Visualizations
              ├──► Clustering
              └──► Signals
```

---

## Key Metrics Explained

### Tier 1: Direct from Fills

| Metric | Formula | Description |
|--------|---------|-------------|
| **Total Volume** | `SUM(price × size)` | Total notional traded |
| **Net PnL** | `SUM(closed_pnl) - SUM(fees)` | Realized profit after fees |
| **Trade Count** | `COUNT(*)` | Number of fills |
| **Maker %** | `maker_fills / total_fills` | Proportion of limit orders |
| **Win Rate** | `winning_closes / total_closes` | % of profitable closes |

### Tier 2: Derived Metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **MTM/TV (Edge)** | `PnL / Volume` | Profit per dollar traded. <10 bps = market maker, >10 bps = directional |
| **Sharpe Ratio** | `mean(daily_pnl) / std(daily_pnl) × √365` | Risk-adjusted returns. >2.0 is excellent |
| **Profit Factor** | `gross_wins / gross_losses` | >1.5 is solid, >2.0 is very good |

### Edge (MTM/TV) Deep Dive

Edge is the most important metric for trader classification:

```
Edge = Net PnL / Total Volume × 10,000 (in basis points)

Examples:
- Edge = 5 bps  → Made $5 per $10,000 traded (likely market maker)
- Edge = 50 bps → Made $50 per $10,000 traded (skilled directional)
- Edge = -20 bps → Lost $20 per $10,000 traded (losing trader)
```

**Why it matters**: High-volume traders with low edge are likely market makers who profit from spreads and rebates, not directional skill. We want to follow traders with HIGH edge.

---

## Trader Classification

### Heuristic Rules

```python
def classify(trader):
    # Liquidators: Primarily execute liquidations
    if liquidation_pct >= 20%:
        return "LIQUIDATOR"

    # HFT/Market Makers: High maker %, low edge
    if maker_pct >= 70% and abs(edge) <= 10 bps:
        return "HFT"

    # Smart Directional: Profitable with skill
    if pnl >= $100K and edge >= 10 bps and sharpe >= 1.0:
        return "SMART_DIRECTIONAL"

    # Everyone else
    return "RETAIL"
```

### Classification Matrix

| Type | Maker % | Edge | PnL | Signal Value |
|------|---------|------|-----|--------------|
| **SMART_DIRECTIONAL** | Any | ≥10 bps | ≥$100K | **Highest** - follow their positions |
| **HFT** | ≥70% | ≤10 bps | Any | Low - profit from spread, not direction |
| **LIQUIDATOR** | Any | Any | Any | Low - opportunistic, not predictive |
| **RETAIL** | Any | Any | Any | Counter-signal potential |

---

## Visualizations Explained

### 1. Trader Type Distribution

**What it shows**: Breakdown of traders by classification

**How to read**:
- Pie chart shows relative number of each type
- Volume bars show which types dominate trading
- PnL bars show which types are profitable overall

**Key insight**: Most traders are RETAIL, but a small % of smart traders capture most profits.

### 2. Edge vs PnL Scatter Plot

**What it shows**: Relationship between trading edge and profitability

**How to read**:
- X-axis: Edge in basis points
- Y-axis: Net PnL
- Colors: Trader types
- Vertical line at 10 bps: Directional trader threshold

**Key insight**: Profitable traders cluster in the upper-right (high edge, high PnL). Market makers cluster around 0 edge.

### 3. PnL Distribution

**What it shows**: How profits/losses are distributed across traders

**How to read**:
- Left skew = more losers than winners
- Median line shows typical trader outcome
- Buckets show exact counts in each range

**Key insight**: Trading is zero-sum minus fees. Most retail traders lose.

### 4. Correlation Heatmap

**What it shows**: How metrics relate to each other

**Key correlations to watch**:
- `PnL vs Edge`: Should be positive (higher edge = more profit)
- `PnL vs Win Rate`: Should be positive
- `Edge vs Maker%`: Often negative (makers have lower edge)
- `Volume vs Fees`: Always positive (more trading = more fees)

### 5. Time Series Dashboard

**What it shows**: Market activity over time

**Panels**:
- Volume trend: Market interest over time
- Fill count: Trading intensity
- Active traders: Participation levels
- Cumulative PnL: Overall market profitability

---

## ML Clustering Analysis

### Why Clustering?

Heuristic classification has limitations:
- Hard thresholds may miss nuanced trader types
- Doesn't discover NEW trader archetypes
- Can't capture complex feature interactions

K-Means clustering finds natural groupings in the data.

### Features Used

| Feature | Why Included |
|---------|--------------|
| `log(volume)` | Trading scale (log to normalize) |
| `maker_pct` | Execution style |
| `win_rate` | Consistency |
| `edge_bps` | Skill level |
| `net_pnl` | Overall performance |

### Interpreting Clusters

After clustering, each cluster is profiled by its average metrics:

```
CLUSTER 0: Market Makers
- High maker % (>80%)
- Low edge (~0 bps)
- Moderate volume

CLUSTER 1: Skilled Directional
- Positive PnL
- High edge (>20 bps)
- Good win rate

CLUSTER 2: Retail Losers
- Negative PnL
- Low win rate
- Negative edge

CLUSTER 3: High-Volume Retail
- High volume
- Mixed results
- Low maker %
```

### Elbow Method

The elbow plot helps choose optimal K:
- X-axis: Number of clusters
- Y-axis: Within-cluster variance (inertia)
- Choose K where the curve "bends" (diminishing returns)

### PCA Projection

PCA reduces dimensions for visualization:
- Each point is a trader
- Colors indicate cluster membership
- Tight clusters = well-separated groups
- Variance explained shows how much info is preserved

---

## Signal Generation

### Smart Money Confluence

**Trigger**: Multiple smart traders position on same side

```sql
-- High conviction signal
WHERE smart_trader_count >= 3
  AND long_short_ratio >= 2.0  -- or <= 0.5 for bearish
```

**Interpretation**: When 3+ smart traders go long on a coin with L/S ratio > 2x, it's a bullish signal.

### Whale Positions

**Trigger**: Smart trader opens >$500K position

**Interpretation**: Large positions from proven traders may move markets.

### Fresh Wallet Activity

**Trigger**: New wallet (<7 days) with volume >2x average

**Interpretation**: Could be:
- New alpha source
- Insider trading
- Wash trading (caution)

### Counter-Trading Retail

**Trigger**: Extreme retail positioning (>80% one side)

**Interpretation**: Retail is often wrong at extremes. Consider opposite position.

---

## How to Use This Analysis

### For Trading

1. **Identify smart traders** using the classification
2. **Monitor their positions** via smart money signals
3. **Track confluence** when multiple smart traders align
4. **Avoid retail traps** by watching retail positioning

### For Research

1. **Validate classification** against known traders
2. **Backtest signals** on historical data
3. **Refine clusters** with additional features
4. **Track metrics** over time for regime changes

### For Risk Management

1. **Monitor liquidation spikes** for market stress
2. **Track fee destruction** traders
3. **Watch for volume anomalies**
4. **Identify concentrated positions**

---

## Metrics Reference Card

| Metric | Good Value | Great Value | Warning |
|--------|------------|-------------|---------|
| **Edge** | >10 bps | >50 bps | <-10 bps |
| **Sharpe** | >1.0 | >2.0 | <0 |
| **Win Rate** | >50% | >60% | <40% |
| **Profit Factor** | >1.5 | >2.0 | <1.0 |
| **Maker %** | 30-70% | Context-dependent | - |

---

## Limitations

1. **Survivorship bias**: Only analyzing active traders
2. **Time period**: Results depend on market regime
3. **Classification thresholds**: Heuristics may not fit all markets
4. **Latency**: Analysis is retrospective, not real-time
5. **Data quality**: Depends on fill data accuracy

---

## Next Steps

1. **Real-time signals**: Connect to WebSocket for live alerts
2. **Backtesting**: Validate signals on historical data
3. **Position tracking**: Reconstruct trader positions over time
4. **ML models**: Train classifiers on labeled trader data
5. **API integration**: Serve signals to trading systems
