# Hyperliquid Data Providers Research

## Goal
Build a dashboard for trader insights on Hyperliquid: PnL, size, buying patterns, trade history.

---

## Data Source Comparison

| Provider | Data Type | Coverage | Access Method | Cost | Best For |
|----------|-----------|----------|---------------|------|----------|
| **Hyperliquid S3** | Raw trades, L2 books | Apr 2023 → present | AWS S3 (requester pays) | Transfer costs only | Bulk historical analysis |
| **Hyperliquid API** | Real-time + last 10k fills | Live + limited history | REST API | Free | Real-time tracking |
| **Allium** | Enriched trades, PnL, metrics | May 2023 → present | API, Snowflake, Databricks | Paid (pricing unlisted) | Production analytics |
| **HypurrScan** | On-chain explorer data | Full history | Web UI (API unclear) | Free (web) | Address lookup, auctions |
| **Nansen** | PnL leaderboard rankings | Current | REST API | Paid (credits) | Trader rankings |
| **Thunderhead/ASXN** | Aggregated stats | Historical | Self-hosted or stats.hyperliquid.xyz | Free (open source) | Quick dashboards |
| **Dwellir** | Raw archival + streaming | Jan 2025 → present | Contact for access | Unknown | Enterprise/custom |

---

## 1. Hyperliquid Native S3 (Already Set Up)

### Trade Data Buckets

```
s3://hl-mainnet-node-data/
├── node_trades/          # Mar 22 - May 25, 2025 (basic)
├── node_fills/           # May 25 - Jul 27, 2025 (with PnL)
├── node_fills_by_block/  # Jul 27, 2025 → current (full context)
└── replica_cmds/         # Jan 2025 → (complete L1 state)
```

### Fill Record Fields

| Field | Description |
|-------|-------------|
| `user` | Wallet address |
| `coin` | Trading symbol |
| `px` | Execution price |
| `sz` | Fill size |
| `side` | "B" (Buy) or "S" (Sell) |
| `time` | Unix timestamp (ms) |
| `dir` | "Open Long", "Open Short", "Close Long", "Close Short" |
| `startPosition` | Position before fill |
| `closedPnl` | Realized PnL (on close) |
| `fee` | Trading fee |
| `feeToken` | Fee currency |
| `hash` | Transaction hash |
| `oid` | Order ID |
| `crossed` | Crossed spread (taker) |
| `tid` | Trade ID |
| `builder_fee` | Builder fee (newer data) |

### Pros
- Complete raw data with trader addresses
- Cheapest option (just S3 transfer costs)
- Full historical coverage

### Cons
- Requires parsing LZ4 compressed files
- Must build your own aggregation pipeline
- ~1% of high-volume traders missing pre-March 2025

---

## 2. Hyperliquid Native API

**Endpoint**: `POST https://api.hyperliquid.xyz/info`

### Key Endpoints for Trader Analytics

```python
# User fills (last 2000)
{"type": "userFills", "user": "0x..."}

# Fills by time range (max 2000, last 10k available)
{"type": "userFillsByTime", "user": "0x...", "startTime": 1234567890000}

# Portfolio history (PnL over time)
{"type": "portfolio", "user": "0x..."}

# Clearinghouse state (positions, margin)
{"type": "clearinghouseState", "user": "0x..."}

# User fees and volume tier
{"type": "userFees", "user": "0x..."}
```

### Limitations
- **10,000 fill limit** per address (can't backfill beyond)
- 500 element response limit
- Rate limits apply

### Pros
- Free, official API
- Real-time data
- Direct position/margin data

### Cons
- Limited history (10k fills per user)
- Must poll each address individually
- No bulk export

---

## 3. Allium

**URL**: https://hyperliquid.allium.so/

### Available Tables

**Enriched Data**:
- `hyperliquid.dex.trades` - Trades with token metadata, builder fees
- `hyperliquid.metrics.overview` - Daily txns, users, TVL
- `hyperliquid.assets.transfers` - Deposits/withdrawals

**Raw Data**:
- `hyperliquid.raw.fills` - All fills
- `hyperliquid.raw.orders` - Order data (from Mar 2025)
- `hyperliquid.raw.blocks`, `transactions`, `tokens`
- `hyperliquid.raw.builder_*` - Builder analytics
- `hyperliquid.raw.register_referral`, `set_referrer`

### API Endpoints

```
clearinghouseState, openOrders, userFees, userVaultEquities,
subAccounts, frontendOpenOrders, webData2, vaultSummaries...
```

### Access Methods
- REST API
- Snowflake datashare
- Databricks
- Google Cloud
- Kafka/Pub-Sub streaming

### Limitations
- ~4,000 traders (~1%) missing historical trades pre-March 2025
- Orders only from when they started running nodes
- Pricing not public

### Pros
- Pre-computed analytics (PnL, Volume, Liquidations)
- SQL access via data warehouses
- Near real-time streaming option

### Cons
- Paid service
- Same backfill gaps as native API

---

## 4. HypurrScan

**URL**: https://hypurrscan.io/

### Features
- HyperLiquid L1 explorer
- Dutch auction tracking
- TWAP order monitoring
- Address transaction history
- Real-time token data
- Millisecond-level granularity

### Data Available
- Transaction history by address
- Holdings and balances
- Token deployments
- Fund flows between addresses

### Access
- Web UI only (API access unclear)
- RPC endpoint: `http://rpc.hypurrscan.io`

### Pros
- Free web interface
- Good for manual address research
- Validator (trusted source)

### Cons
- No clear API for bulk data
- Web scraping would be required for automation

---

## 5. Nansen API

**URL**: https://docs.nansen.ai/api/hyperliquid-apis/perp-pnl-leaderboard

### PnL Leaderboard Endpoint

```
POST https://api.nansen.ai/api/v1/tgm/perp-pnl-leaderboard
```

### Fields
- `pnl_usd_realised` / `unrealised`
- `roi_total` / `realised` / `unrealised`
- `position_value_usd`
- `max_balance_held_usd`
- `net_flow_usd`
- `trade_count`

### Pros
- Pre-computed trader rankings
- Filterable by PnL, position value
- Per-token breakdowns

### Cons
- Paid API (credit-based)
- Limited to leaderboard data
- No raw trade history

---

## 6. Thunderhead Labs (Open Source)

**GitHub**: https://github.com/thunderhead-labs/hyperliquid-stats
**Live**: https://stats.hyperliquid.xyz/

### Endpoints (32+)

```
GET /hyperliquid/user_pnl              # Daily PnL all users
GET /hyperliquid/cumulative_user_pnl   # Cumulative PnL
GET /hyperliquid/hlp_liquidator_pnl    # Liquidator PnL
GET /hyperliquid/total_users           # User count
GET /hyperliquid/total_usd_volume      # Volume
GET /hyperliquid/volume_by_coin        # Per-coin volume
GET /hyperliquid/largest_users_by_volume
GET /hyperliquid/open_interest_by_coin
GET /hyperliquid/funding_by_coin
...
```

### Architecture
```
Hyperliquid S3 → PostgreSQL → FastAPI
```

### Pros
- Open source (can fork/modify)
- Self-hostable
- Uses same S3 data we have access to
- Pre-built aggregations

### Cons
- Must run your own infrastructure
- May need modifications for specific trader analytics

---

## 7. Dwellir

**URL**: https://www.dwellir.com/docs/hyperliquid/trade-data

### Data Formats

| Period | Format | Content |
|--------|--------|---------|
| Mar-May 2025 | node_trades | Basic execution info |
| May-Jul 2025 | node_fills | +PnL, fees, direction |
| Jul 2025+ | node_fills_by_block | +Block context, builder info |
| Jan 2025+ | replica_cmds | Complete L1 state |

### Access
- Contact: ben@dwellir.com
- REST APIs, bulk exports, real-time streaming

### Pros
- Complete archival data
- Custom pipelines available
- Real-time streaming

### Cons
- Requires contacting for access
- Likely enterprise pricing

---

## Recommendation

### For Your Dashboard (Trader PnL, Size, Patterns)

**Option A: Build Your Own (Lower Cost)**
1. Use **Hyperliquid S3** data you already have access to
2. Fork **thunderhead-labs/hyperliquid-stats** as starting point
3. Store in PostgreSQL/ClickHouse
4. Add custom trader-level aggregations

**Data needed**:
- `node_fills_by_block` for Jul 2025+ (complete)
- `node_fills` for May-Jul 2025
- `node_trades` for Mar-May 2025
- Backfill older via Hyperliquid API (limited)

**Option B: Use Allium (Faster to Market)**
1. Pay for Allium access
2. Query via SQL (Snowflake/Databricks)
3. Pre-computed PnL, volume, patterns
4. Focus on dashboard, not data pipeline

**Option C: Hybrid**
1. Use S3 for bulk historical
2. Use Hyperliquid API for real-time
3. Use HypurrScan for address lookup
4. Build aggregation layer yourself

---

## Data Schema for Dashboard

Based on fills data, you can compute:

```sql
-- Per-trader metrics
SELECT
  user_address,
  COUNT(*) as trade_count,
  SUM(CASE WHEN dir LIKE 'Open%' THEN sz * px ELSE 0 END) as total_volume_opened,
  SUM(closedPnl) as realized_pnl,
  SUM(fee) as total_fees,
  AVG(sz * px) as avg_trade_size,
  COUNT(DISTINCT coin) as coins_traded,
  MIN(time) as first_trade,
  MAX(time) as last_trade
FROM fills
GROUP BY user_address;

-- Buying patterns (time of day, day of week)
-- Position sizing over time
-- Win rate (closedPnl > 0 vs < 0)
-- Holding duration (time between open and close)
-- Leverage analysis (from clearinghouse snapshots)
```

---

## HyperCore Tools Directory (Official Ecosystem)

### Analytics - Perps & Order Book

| Tool | URL | What It Does | Relevance |
|------|-----|--------------|-----------|
| **ASXN** | hyperscreener.asxn.xyz | Staking, auctions, token holders, ecosystem metrics | ⭐ Good for macro trends |
| **Artemis** | app.artemis.xyz/project/hyperliquid | Protocol-level analytics | Overview dashboards |
| **Coinalyze** | coinalyze.net/markets/?exchange=H | Open interest, funding, liquidations | Market structure |
| **DefiLlama** | defillama.com/perps/chains/hyperliquid | TVL tracking (order book methodology) | TVL benchmarking |
| **Dune** | dune.com/uwusanauwu/perps | Community SQL dashboards | ⭐ Customizable queries |
| **HL Metrics** | hl-metrics.xyz | 24h rolling volume | Quick volume check |
| **HyperDash** | hyperdash.info | Leaderboard trader positions | ⭐ Trader tracking |
| **Hyperscan** | hyperscan.fun | Block explorer | Transaction lookup |
| **Hypervisor** | hypervisor.gg | Trading analytics | Trader metrics |
| **Laevitas** | app.laevitas.ch/.../HYPERLIQUID/screener | Derivatives screener, term structure | Options/perps analysis |
| **Velo** | velo.xyz/futures | Futures analytics | Cross-exchange comparison |

### Analytics - USDC Bridge (Arbitrum)

| Tool | URL | Focus |
|------|-----|-------|
| **Flipside** | flipsidecrypto.xyz/pine/hyperliquid-bridge-metrics | Bridge volume, unique depositors |
| **Parsec** | parsec.fi/arb/address/0x2df1c... | Real-time bridge monitoring |
| **Dune (Mogie)** | dune.com/mogie/hyperliquid-flows | Inflow/outflow analysis |
| **Dune (KamBenbrik)** | dune.com/kambenbrik/hyperliquid | General metrics |
| **Dune (Hashed)** | dune.com/hashed_official/usdc-on-hyperliquid | USDC supply tracking |
| **Dune (X3Research)** | dune.com/x3research/hyperliquid | Cross-chain flows |

### SDKs & APIs

| Resource | URL | Language | Notes |
|----------|-----|----------|-------|
| **Official Python SDK** | github.com/hyperliquid-dex/hyperliquid-python-sdk | Python | ⭐ Best maintained |
| **Official Rust SDK** | github.com/hyperliquid-dex/hyperliquid-rust-sdk | Rust | Less maintained |
| **nktkas SDK** | github.com/nktkas/hyperliquid | TypeScript | Community |
| **nomeida SDK** | github.com/nomeida/hyperliquid | TypeScript | Community |
| **CCXT** | docs.ccxt.com/#/exchanges/hyperliquid | Multi-lang | Standard exchange API |
| **Dwellir gRPC** | dwellir.com/docs/hyperliquid/grpc | Any | High-performance |
| **Dwellir WebSocket** | dwellir.com/docs/hyperliquid/websocket-api | Any | Real-time streaming |
| **Hydromancer** | docs.hydromancer.xyz | Any | ⭐ Non-rate-limited |

### Block Explorers

| Explorer | URL | Specialty |
|----------|-----|-----------|
| **Official** | app.hyperliquid.xyz/explorer | Canonical source |
| **Flowscan** | flowscan.xyz | Clean UI |
| **HypurrScan** | hypurrscan.io | ⭐ Auctions, TWAPs, ms-level data |

### Indexing & Data Infrastructure

| Service | URL | Access | Best For |
|---------|-----|--------|----------|
| **Allium** | docs.allium.so/.../hyperliquid | SQL (Snowflake/Databricks) | ⭐ Production analytics |
| **HypeDexer** | hypedexer.com | API | DEX-specific indexing |

### Security & Custody

| Service | URL | Type |
|---------|-----|------|
| **FalconX** | falconx.io | Qualified custodian |
| **HyperSig** | hypersig.xyz | Multisig wallet |

---

## Tool Recommendations for Trader Dashboard

### Must-Have
1. **Hyperliquid S3** - Raw fills data (you have this)
2. **Official Python SDK** - Real-time API calls
3. **HypurrScan** - Address lookup, manual verification

### Worth Exploring
1. **Hydromancer** - Non-rate-limited APIs could be huge for bulk queries
2. **HyperDash** - Already tracks leaderboard traders (competitor intel)
3. **Dune** - Free SQL queries, can prototype metrics before building

### Skip For Now
- Laevitas/Velo/Coinalyze - More for market structure, not trader analytics
- FalconX/HyperSig - Custody, not relevant to dashboard

---

## Sources

- [Allium Hyperliquid Docs](https://docs.allium.so/historical-data/supported-blockchains/hyperliquid/overview)
- [Allium Hyperliquid Portal](https://hyperliquid.allium.so/)
- [HypurrScan](https://hypurrscan.io/)
- [Nansen PnL Leaderboard API](https://docs.nansen.ai/api/hyperliquid-apis/perp-pnl-leaderboard)
- [Thunderhead hyperliquid-stats](https://github.com/thunderhead-labs/hyperliquid-stats)
- [ASXN Dashboard](https://stats.hyperliquid.xyz/)
- [Dwellir Trade Data Docs](https://www.dwellir.com/docs/hyperliquid/trade-data)
- [Hyperliquid Official API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [Hyperliquid Historical Data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data)
