# Hyperliquid S3 Data Reference

## Root Buckets

```
s3://hl-mainnet-node-data/          # Node-streamed data (blocks, trades, fills)
s3://hyperliquid-archive/           # Periodic archives (orderbook, asset contexts)
```

All require: `--request-payer requester`

---

## hl-mainnet-node-data

```
s3://hl-mainnet-node-data/
├── explorer_blocks/          # Raw blocks         (Feb 2023+)  MessagePack+LZ4
├── node_trades/hourly/       # Parsed trades      (Mar 2025+)  JSON+LZ4
├── node_fills/hourly/        # Fills + PnL        (May 2025+)  JSON+LZ4
├── node_fills_by_block/hourly/  # Fills by block  (Jul 2025+)  JSON+LZ4
├── replica_cmds/             # Raw L1 commands    (Jan 2025+)  Various
└── misc_events_by_block/hourly/ # Liquidations etc (Sep 2025+) JSON+LZ4
```

## hyperliquid-archive

```
s3://hyperliquid-archive/
├── market_data/              # L2 orderbook snapshots  (Apr 2023+)  JSON+LZ4
├── asset_ctxs/               # Asset contexts          (Apr 2023+)  CSV+LZ4
└── Testnet/                  # Testnet data
```

---

## 1. explorer_blocks

### Directory Structure
```
s3://hl-mainnet-node-data/explorer_blocks/
├── 0/                           # blocks 0 - 99,999,999
│   ├── 0/                       # blocks 0 - 99,999
│   │   ├── 1000.rmp.lz4        # blocks 901-1000
│   │   ├── 1100.rmp.lz4        # blocks 1001-1100
│   │   └── ...
│   ├── 100000/                  # blocks 100,000 - 199,999
│   └── ...
├── 100000000/                   # blocks 100M - 199M
│   ├── 100000000/
│   │   ├── 100000100.rmp.lz4
│   │   └── ...
└── 800000000/                   # latest
```

**Pattern**: `{100M prefix}/{1M prefix}/{end_block}.rmp.lz4`
**Batch**: 100 blocks per file

### Data Format
```python
# Decompress: unlz4 file.rmp.lz4 file.rmp
# Parse: msgpack.unpack(open('file.rmp', 'rb'))

[
  {
    "header": {
      "block_time": "2023-11-13T13:34:22.255707",
      "height": 100000001,
      "hash": "0x...",
      "proposer": "..."
    },
    "txs": [
      {
        "user": "0x31ca8395cf837de08b24da3f660e77761dfb974b",
        "raw_tx_hash": "0x...",
        "error": null,
        "actions": [
          {
            "type": "order",
            "orders": [{"a": 0, "b": true, "p": "36916", "s": "0.1", "r": false, "t": {...}}],
            "grouping": "na"
          }
        ]
      }
    ]
  }
]
```

### Action Types
| Type | Fields |
|------|--------|
| `order` | `a` (asset), `b` (buy), `p` (price), `s` (size), `r` (reduceOnly), `t` (type) |
| `cancel` | `a` (asset), `o` (orderId) |
| `connect` | `chain`, `agent`, `agentAddress` |
| `SetGlobalAction` | `pxs` (oracle prices) |

---

## 2. node_trades

### Directory Structure
```
s3://hl-mainnet-node-data/node_trades/hourly/
├── 20250322/
│   ├── 00/
│   │   └── *.lz4
│   ├── 01/
│   └── ...23/
├── 20250323/
└── ...
```

**Pattern**: `{YYYYMMDD}/{HH}/*.lz4`

### Data Format
```python
# JSONL (one JSON per line) + LZ4
{
  "coin": "BTC",
  "side": "B",
  "px": "67500.5",
  "sz": "0.1",
  "time": 1699012345678,
  "hash": "0x...",
  "tid": 12345678,
  "users": ["0xbuyer...", "0xseller..."]
}
```

---

## 3. node_fills

### Directory Structure
```
s3://hl-mainnet-node-data/node_fills/hourly/
├── 20250525/
│   ├── 00/
│   ├── 01/
│   └── ...
└── ...
```

**Pattern**: `{YYYYMMDD}/{HH}/*.lz4`

### Data Format
```python
# JSONL + LZ4
{
  "coin": "BTC",
  "side": "B",
  "px": "67500.5",
  "sz": "0.1",
  "time": 1699012345678,
  "hash": "0x...",
  "oid": 12345678,
  "tid": 87654321,
  "fee": "3.37",
  "feeToken": "USDC",
  "closedPnl": "125.50",
  "startPosition": "0.5",
  "dir": "Open Long",
  "crossed": true,
  "user": "0x31ca8395cf837de08b24da3f660e77761dfb974b"
}
```

---

## 4. node_fills_by_block

### Directory Structure
```
s3://hl-mainnet-node-data/node_fills_by_block/hourly/
├── 20250727/
│   ├── 00/
│   └── ...
└── ...
```

**Pattern**: `{YYYYMMDD}/{HH}/*.lz4`

### Data Format
Same as node_fills, organized by block height.

---

## 5. market_data (L2 Orderbook)

### Directory Structure
```
s3://hyperliquid-archive/market_data/
├── 20230415/
│   ├── 0/
│   │   └── l2Book/
│   │       ├── BTC.lz4
│   │       ├── ETH.lz4
│   │       └── ...
│   ├── 1/
│   └── ...23/
└── ...
```

**Pattern**: `{YYYYMMDD}/{HH}/l2Book/{COIN}.lz4`

### Data Format
```python
# JSON + LZ4
{
  "coin": "BTC",
  "time": 1699012345678,
  "levels": [
    {"px": "67500.0", "sz": "1.5", "n": 3},  # bids
    ...
  ]
}
```

---

## Quick Commands

```bash
# List top-level structure
AWS_PROFILE=trevor aws s3 ls s3://hl-mainnet-node-data/ --request-payer requester

# Sample explorer_blocks
AWS_PROFILE=trevor aws s3 ls "s3://hl-mainnet-node-data/explorer_blocks/0/0/" --request-payer requester | head -5

# Download single file
AWS_PROFILE=trevor aws s3 cp "s3://hl-mainnet-node-data/explorer_blocks/0/0/1000.rmp.lz4" . --request-payer requester

# Decompress
unlz4 file.rmp.lz4 file.rmp      # MessagePack
unlz4 file.lz4 file.json         # JSON
```

---

## Size Estimates

| Bucket | Compressed | Files |
|--------|-----------|-------|
| `explorer_blocks` | ~3-4 TB | ~8M |
| `node_trades` | ~300-500 GB | ~6K |
| `node_fills` | ~200-400 GB | ~4K |
| `market_data` | ~500GB-1TB | ~100K |
