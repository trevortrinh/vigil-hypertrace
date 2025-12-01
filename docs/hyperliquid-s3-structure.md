# Hyperliquid S3 Data Structure

## Access Configuration

```bash
aws s3 cp s3://BUCKET/PATH /local/path --request-payer requester --profile trevor
```

- **Region**: us-east-1
- **Profile**: trevor
- **Requester pays**: Yes (you pay transfer costs)

---

## Bucket: `hyperliquid-archive`

### Top-level directories
```
hyperliquid-archive/
├── Testnet/
├── asset_ctxs/
└── market_data/
```

### `market_data/`

**Date range**: 2023-04-15 → 2025-11-02 (and growing)

**Structure**:
```
market_data/{YYYYMMDD}/{hour}/l2Book/{COIN}.lz4
```

**Example**:
```
market_data/20230916/9/l2Book/SOL.lz4
```

**Hours**: 0-23 (UTC)

**Coins available (Sept 2023 - 50 coins)**:
```
AAVE, APE, APT, ARB, ATOM, AVAX, BANANA, BCH, BLZ, BNB,
BTC, CFX, COMP, CRV, CYBER, DOGE, DOT, DYDX, ETH, FRIEND,
FTM, FXS, GMX, HPOS, INJ, LDO, LINK, LTC, MATIC, MKR,
OP, OX, RLB, RNDR, RUNE, SEI, SHIA, SNX, SOL, STX,
SUI, TRX, UNI, UNIBOT, WLD, XRP, YGG, ZRO, kPEPE, kSHIB
```

**Coins available (Nov 2025 - 184 coins)**:
```
0G, 2Z, AAVE, ACE, ADA, AI16Z, AIXBT, ALGO, ALT, ANIME,
APE, APEX, APT, AR, ARB, ARK, ASTER, ATOM, AVAX, AVNT,
BABY, BANANA, BCH, BERA, BIGTIME, BIO, BLAST, BLUR, BNB, BOME,
... (184 total)
```

**Data format**: LZ4 compressed JSON lines

**Sample record**:
```json
{
  "time": "2023-09-16T09:00:01.039593170",
  "ver_num": 1,
  "raw": {
    "channel": "l2Book",
    "data": {
      "coin": "SOL",
      "time": 1694854799647,
      "levels": [
        [
          {"px": "19.107", "sz": "633.53", "n": 2},
          {"px": "19.105", "sz": "6114.52", "n": 2}
        ],
        [
          {"px": "19.113", "sz": "625.91", "n": 3},
          {"px": "19.117", "sz": "5731.08", "n": 2}
        ]
      ]
    }
  }
}
```

**Fields**:
- `time`: ISO timestamp with nanosecond precision
- `ver_num`: Version number
- `raw.channel`: Always "l2Book"
- `raw.data.coin`: Coin symbol
- `raw.data.time`: Epoch milliseconds
- `raw.data.levels[0]`: Bids (descending price)
- `raw.data.levels[1]`: Asks (ascending price)
- `px`: Price
- `sz`: Size
- `n`: Number of orders at this level

### `asset_ctxs/`

**Date range**: 2023-05-20 → present

**Structure**:
```
asset_ctxs/{YYYYMMDD}.csv.lz4
```

**Example**:
```
asset_ctxs/20230520.csv.lz4
```

**Data format**: LZ4 compressed CSV

---

## Bucket: `hl-mainnet-node-data`

### Top-level directories
```
hl-mainnet-node-data/
├── explorer_blocks/
├── misc_events_by_block/
├── node_fills/
├── node_fills_by_block/
├── node_trades/
└── replica_cmds/
```

### `node_fills_by_block/hourly/`

**Date range**: 2025-07-27 → 2025-11-28 (current, daily updates)

**Structure**:
```
node_fills_by_block/hourly/{YYYYMMDD}/
```

**Description**: Current fills format, organized by block

### `node_fills/`

**Description**: Legacy fills in API format (older data)

### `node_trades/`

**Description**: Legacy trades in non-API format (older data)

### `explorer_blocks/`

**Structure**:
```
explorer_blocks/{block_range}/
```

**Block ranges**:
```
0/
100000000/
200000000/
300000000/
400000000/
...
```

**Description**: Historical explorer blocks organized by 100M block ranges

### `replica_cmds/`

**Date range**: 2025-01-12 → present

**Structure**:
```
replica_cmds/{ISO_TIMESTAMP}/
```

**Examples**:
```
replica_cmds/2025-01-12T11:46:44Z/
replica_cmds/2025-01-26T12:18:22Z/
replica_cmds/2025-02-08T10:31:02Z/
```

**Description**: L1 transactions

### `misc_events_by_block/`

**Description**: Miscellaneous events organized by block

---

## Quick Reference

| Data Type | Bucket | Path Pattern | Date Range |
|-----------|--------|--------------|------------|
| L2 Order Book | hyperliquid-archive | `market_data/{date}/{hour}/l2Book/{coin}.lz4` | 2023-04-15 → present |
| Asset Context | hyperliquid-archive | `asset_ctxs/{date}.csv.lz4` | 2023-05-20 → present |
| Fills (current) | hl-mainnet-node-data | `node_fills_by_block/hourly/{date}/` | 2025-07-27 → present |
| Fills (legacy) | hl-mainnet-node-data | `node_fills/` | older |
| Trades (legacy) | hl-mainnet-node-data | `node_trades/` | older |
| Explorer Blocks | hl-mainnet-node-data | `explorer_blocks/{block_range}/` | block 0 → present |
| L1 Transactions | hl-mainnet-node-data | `replica_cmds/{timestamp}/` | 2025-01-12 → present |

---

## Example Commands

```bash
# List available dates for market data
aws s3 ls s3://hyperliquid-archive/market_data/ --request-payer requester --profile trevor

# List coins for a specific date/hour
aws s3 ls s3://hyperliquid-archive/market_data/20230916/9/l2Book/ --request-payer requester --profile trevor

# Download a single file
aws s3 cp s3://hyperliquid-archive/market_data/20230916/9/l2Book/SOL.lz4 /tmp/SOL.lz4 --request-payer requester --profile trevor

# Decompress
unlz4 --rm /tmp/SOL.lz4

# Download entire day for one coin
aws s3 cp s3://hyperliquid-archive/market_data/20230916/ ./data/20230916/ --recursive --request-payer requester --profile trevor --exclude "*" --include "*/l2Book/BTC.lz4"
```
