# Hyperliquid Data Reference

## S3 Buckets

```
s3://hl-mainnet-node-data/          # Node-streamed data
s3://hyperliquid-archive/           # Periodic archives
```

All require: `--request-payer requester`

## Data Sources by Period

| Period | Source | Format | What's Available |
|--------|--------|--------|------------------|
| Feb 2023 - Mar 2025 | `explorer_blocks/` | MessagePack+LZ4 | Orders only (must reconstruct fills) |
| Mar 2025 - May 2025 | `node_trades/hourly/` | JSON+LZ4 | Trades |
| May 2025 - Jul 2025 | `node_fills/hourly/` | JSON+LZ4 | Fills + PnL |
| **Jul 2025 - Present** | **`node_fills_by_block/hourly/`** | **JSON+LZ4** | **Fills + PnL (recommended)** |

## node_fills_by_block (Primary Source)

**We use this.** Complete fill data with PnL, fees, position tracking.

```
s3://hl-mainnet-node-data/node_fills_by_block/hourly/
├── 20250727/
│   ├── 00/
│   │   └── *.lz4
│   ├── 01/
│   └── ...23/
└── ...
```

### Fill Schema

```json
{
  "coin": "BTC",
  "side": "B",
  "px": "67500.5",
  "sz": "0.1",
  "time": 1699012345678,
  "dir": "Open Long",
  "startPosition": "0.5",
  "closedPnl": "125.50",
  "fee": "3.37",
  "feeToken": "USDC",
  "crossed": true,
  "hash": "0x...",
  "oid": 12345678,
  "tid": 87654321,
  "user": "0x31ca8395..."
}
```

### Field Descriptions

| Field | Description |
|-------|-------------|
| `coin` | Asset symbol |
| `side` | B=Buy, A=Sell |
| `px` | Execution price |
| `sz` | Size |
| `time` | Unix timestamp (ms) |
| `dir` | Open Long, Open Short, Close Long, Close Short |
| `startPosition` | Position before this fill |
| `closedPnl` | Realized PnL (on closes) |
| `fee` | Fee paid (negative = rebate) |
| `crossed` | true=taker, false=maker |
| `user` | Wallet address |

## Parsing

```python
import lz4.frame
import json

def parse_fills(filepath):
    with open(filepath, 'rb') as f:
        compressed = f.read()
    decompressed = lz4.frame.decompress(compressed)
    for line in decompressed.decode().strip().split('\n'):
        yield json.loads(line)
```

## Size Estimates

| Source | Compressed Size | Files |
|--------|-----------------|-------|
| `node_fills_by_block` (Jul 2025+) | ~200-400 GB | ~4K |
| `node_fills` (May-Jul 2025) | ~100-200 GB | ~2K |
| `explorer_blocks` (full history) | ~3-4 TB | ~8M |

## AWS Commands

```bash
# List available dates
aws s3 ls s3://hl-mainnet-node-data/node_fills_by_block/hourly/ --request-payer requester

# Download single day
aws s3 sync \
  s3://hl-mainnet-node-data/node_fills_by_block/hourly/20251101/ \
  ./data/20251101/ \
  --request-payer requester

# Sample file
aws s3 cp \
  s3://hl-mainnet-node-data/node_fills_by_block/hourly/20251101/00/0.lz4 \
  . --request-payer requester
```

## Other Data (Reference)

### explorer_blocks (Raw Blocks)

Full block data with orders. Required only if you need pre-May 2025 history.

```
s3://hl-mainnet-node-data/explorer_blocks/
├── 0/                      # Blocks 0-99,999,999
│   ├── 0/                  # Blocks 0-99,999
│   │   ├── 1000.rmp.lz4   # Blocks 901-1000
```

Format: MessagePack + LZ4

### market_data (L2 Orderbook)

Hourly orderbook snapshots per coin.

```
s3://hyperliquid-archive/market_data/
├── 20230415/
│   ├── 0/
│   │   └── l2Book/
│   │       ├── BTC.lz4
│   │       └── ETH.lz4
```
