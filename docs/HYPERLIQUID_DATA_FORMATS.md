# Hyperliquid Data Formats: Raw vs Convenient

## TL;DR

| Period | Data Available | Format | Effort to Use |
|--------|---------------|--------|---------------|
| **Feb 2023 - Mar 2025** | Orders only | Raw blocks (MessagePack) | High - must reconstruct fills |
| **Mar 2025 - May 2025** | Orders + Trades | Parsed JSON | Medium - trades available |
| **May 2025 - Present** | Orders + Fills + PnL | Parsed JSON | Low - ready to use |

---

## Raw Format (Feb 2023 - Present)

### Source
```
s3://hl-mainnet-node-data/explorer_blocks/
```

### Structure
```
explorer_blocks/
├── 0/                      # Blocks 0-99,999,999
│   ├── 0/                  # Blocks 0-99,999
│   │   ├── 1000.rmp.lz4   # Blocks 901-1000 (batched by 100)
│   │   └── ...
│   └── 100000/            # Blocks 100,000-199,999
├── 100000000/             # Blocks 100M-199M
└── ...
```

### File Format
- **Compression**: LZ4
- **Serialization**: MessagePack (`.rmp`)
- **Batch size**: 100 blocks per file

### Schema
```json
[
  {
    "header": {
      "block_time": "2023-02-26T17:41:39.942659",
      "height": 901,
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
            "orders": [{
              "a": 0,        // asset ID (0=BTC, 1=ETH, etc)
              "b": true,     // true=buy, false=sell
              "p": "36916",  // price
              "s": "0.1",    // size
              "r": false,    // reduce only
              "t": {"limit": {"tif": "Alo"}}  // order type
            }],
            "grouping": "na"
          }
        ]
      }
    ]
  }
]
```

### Action Types in Raw Format
| Type | Description | Contains |
|------|-------------|----------|
| `order` | Place order | asset, side, price, size, type |
| `cancel` | Cancel order | asset ID, order ID |
| `connect` | Link agent wallet | chain, agent address |
| `SetGlobalAction` | Oracle price update | bid/ask per asset |

### What's Missing
- **No fills** - must infer from order matching
- **No PnL** - must calculate from position changes
- **No fees** - not included

---

## Convenient Format (Mar 2025 - Present)

### Sources

#### 1. node_trades (Mar 22, 2025+)
```
s3://hl-mainnet-node-data/node_trades/hourly/{YYYYMMDD}/{HH}/
```

Basic trade records with:
- Coin, side, price, size
- Buyer/seller addresses
- Transaction hash

#### 2. node_fills (May 25, 2025+)
```
s3://hl-mainnet-node-data/node_fills/hourly/{YYYYMMDD}/{HH}/
```

Enhanced with:
- Closed PnL
- Fee information
- Starting position

#### 3. node_fills_by_block (Jul 27, 2025+)
```
s3://hl-mainnet-node-data/node_fills_by_block/hourly/{YYYYMMDD}/{HH}/
```

Current format with:
- Fills organized by block
- Complete transaction context
- Full audit trail

### Schema (node_fills)
```json
{
  "coin": "BTC",
  "side": "B",
  "time": "2025-05-25T10:30:00.123Z",
  "px": "67500.5",
  "sz": "0.1",
  "hash": "0xabc123...",
  "closedPnl": "125.50",
  "fee": "3.37",
  "feeToken": "USDC",
  "startPosition": "0.5",
  "dir": "Open Long",
  "oid": 12345678,
  "tid": 87654321,
  "side_info": {
    "user": "0x31ca8395cf837de08b24da3f660e77761dfb974b"
  }
}
```

---

## Comparison

| Feature | Raw (explorer_blocks) | Convenient (node_fills) |
|---------|----------------------|------------------------|
| **Date range** | Feb 2023 - Present | May 2025 - Present |
| **User addresses** | ✅ Yes | ✅ Yes |
| **Orders** | ✅ Yes | ❌ No |
| **Fills/Trades** | ❌ Must reconstruct | ✅ Yes |
| **PnL** | ❌ Must calculate | ✅ Yes |
| **Fees** | ❌ No | ✅ Yes |
| **Position tracking** | ❌ Must build | ✅ startPosition field |
| **File format** | MessagePack + LZ4 | JSON + LZ4 |
| **Parsing difficulty** | Medium | Easy |

---

## What We Need To Do

### Option A: Use Convenient Data Only (Recommended Start)

**Scope**: May 2025 - Present (~7 months of data)

```bash
# Download all fills
AWS_PROFILE=trevor aws s3 sync \
  s3://hl-mainnet-node-data/node_fills/hourly/ \
  ./fills/ \
  --request-payer requester

# Or just recent month
AWS_PROFILE=trevor aws s3 sync \
  s3://hl-mainnet-node-data/node_fills/hourly/202511/ \
  ./fills/202511/ \
  --request-payer requester
```

**Effort**: Low - data is ready to use
**Cost**: ~$5-20 for data transfer

### Option B: Hybrid Approach (Full History)

1. **Get all addresses from raw blocks**
   ```python
   # Parse explorer_blocks to extract unique addresses
   addresses = set()
   for block_file in explorer_blocks:
       for tx in block.txs:
           addresses.add(tx.user)
   ```

2. **Backfill fills via API**
   ```python
   # For each address, get up to 10k most recent fills
   for addr in addresses:
       fills = api.userFillsByTime(user=addr, startTime=0)
   ```

3. **Use convenient format for 2025+**
   - Download node_fills for complete recent data

**Effort**: Medium
**Limitation**: API only returns 10k fills per address

### Option C: Full Reconstruction (Complete History)

1. **Download all explorer_blocks** (~4-5 TB estimated)
2. **Build order book replay engine**
3. **Match crossing orders to identify fills**
4. **Calculate positions and PnL**

**Effort**: High (weeks of work)
**When needed**: Only if you need complete fill history for high-volume traders

---

## Practical Recommendation

### Phase 1: Quick Win
- Download `node_fills` from May 2025
- Get all trader addresses and their fills with PnL
- ~7 months of complete data

### Phase 2: Extend History
- Parse `explorer_blocks` to get address list
- Use API to backfill fills (10k limit per address)
- Covers ~99% of traders completely

### Phase 3: If Needed
- Only build full reconstruction if you need:
  - Complete history for the ~4,000 high-volume traders
  - Order-level analysis (not just fills)
  - Order book replay capabilities

---

## Code Examples

### Parse Raw Blocks
```python
import msgpack
import lz4.frame

def parse_explorer_block(filepath):
    with open(filepath, 'rb') as f:
        compressed = f.read()

    decompressed = lz4.frame.decompress(compressed)
    blocks = msgpack.unpackb(decompressed, raw=False)

    for block in blocks:
        for tx in block.get('txs', []):
            user = tx.get('user')
            for action in tx.get('actions', []):
                yield {
                    'block_time': block['header']['block_time'],
                    'user': user,
                    'action_type': action.get('type'),
                    'action': action
                }
```

### Parse Convenient Fills
```python
import json
import lz4.frame

def parse_fills(filepath):
    with open(filepath, 'rb') as f:
        compressed = f.read()

    decompressed = lz4.frame.decompress(compressed)

    for line in decompressed.decode().strip().split('\n'):
        yield json.loads(line)
```

### Backfill via API
```python
import requests

def get_user_fills(address, start_time=0):
    resp = requests.post(
        'https://api.hyperliquid.xyz/info',
        json={
            'type': 'userFillsByTime',
            'user': address,
            'startTime': start_time
        }
    )
    return resp.json()
```

---

## S3 Buckets Summary

| Bucket | Content | Start Date |
|--------|---------|------------|
| `hl-mainnet-node-data/explorer_blocks/` | Raw blocks | Feb 2023 |
| `hl-mainnet-node-data/node_trades/hourly/` | Parsed trades | Mar 2025 |
| `hl-mainnet-node-data/node_fills/hourly/` | Fills with PnL | May 2025 |
| `hl-mainnet-node-data/node_fills_by_block/hourly/` | Fills by block | Jul 2025 |
| `hyperliquid-archive/market_data/` | L2 orderbook | Apr 2023 |

All require `--request-payer requester` flag.

---

## Data Size Estimates

### Estimation Method (Don't recursive list - too expensive!)

**DON'T DO THIS** (slow, expensive):
```bash
# BAD - will cost money and take forever
aws s3 ls s3://bucket/ --summarize --recursive --request-payer requester
```

**DO THIS** - Sample-based estimation:
```bash
# 1. Check folder structure (cheap - just top level)
aws s3 ls s3://hl-mainnet-node-data/explorer_blocks/ --request-payer requester

# 2. Sample a few files to get average size
aws s3 ls "s3://hl-mainnet-node-data/explorer_blocks/0/0/" --request-payer requester | head -20

# 3. Count files in one subfolder
aws s3 ls "s3://hl-mainnet-node-data/explorer_blocks/0/0/" --request-payer requester | wc -l
```

### explorer_blocks Estimate

**Known facts from samples:**
- Block ~1,000 file (Feb 2023): 18 KB compressed
- Block ~100M file (Nov 2023): 606 KB compressed
- Files batch 100 blocks each
- Block time: ~100ms (10 blocks/sec)
- Current block height: ~800M+ (based on folder prefixes)

**Calculation:**
```
Total files ≈ 800M blocks / 100 blocks per file = 8M files

File size varies by activity:
- 2023 (blocks 0-100M): avg ~50KB × 1M files = 50 GB
- 2024 (blocks 100M-400M): avg ~300KB × 3M files = 900 GB
- 2025 (blocks 400M-800M): avg ~600KB × 4M files = 2.4 TB

Total compressed: ~3.4 TB
Decompressed (4x ratio): ~13-15 TB
```

### node_fills Estimate

**Known facts:**
- Hourly files since May 25, 2025
- ~6 months = 180 days × 24 hours = 4,320 files

**Quick size check (one day):**
```bash
aws s3 ls "s3://hl-mainnet-node-data/node_fills/hourly/20251101/" --request-payer requester
```

**Estimate:**
```
If avg file = 50MB compressed:
4,320 files × 50MB = 216 GB compressed
Decompressed: ~500GB - 1TB
```

### node_trades Estimate

**Known facts:**
- Hourly files since Mar 22, 2025
- ~8 months = 240 days × 24 hours = 5,760 files

**Estimate:**
```
Similar to node_fills, likely: 300-500 GB compressed
```

### Summary Table

| Bucket | Est. Compressed | Est. Decompressed | Files |
|--------|----------------|-------------------|-------|
| `explorer_blocks` | **~3-4 TB** | ~13-15 TB | ~8M |
| `node_trades` | ~300-500 GB | ~1-2 TB | ~6K |
| `node_fills` | ~200-400 GB | ~500GB-1TB | ~4K |
| `market_data` | ~500GB-1TB | ~2-4 TB | ~100K |

### AWS Transfer Cost Estimate

```
S3 Data Transfer (requester pays):
- $0.09 per GB (first 10TB)
- $0.085 per GB (next 40TB)

explorer_blocks full download:
~3.5TB × $0.09 = ~$315

node_fills full download:
~300GB × $0.09 = ~$27

Recommended: Start with node_fills ($27) not explorer_blocks ($315)
```

### Smart Sampling Commands

```bash
# Check how many top-level prefixes exist
aws s3 ls s3://hl-mainnet-node-data/explorer_blocks/ --request-payer requester

# Sample file sizes from different time periods
# Early 2023
aws s3 ls "s3://hl-mainnet-node-data/explorer_blocks/0/0/" --request-payer requester | head -5

# Late 2023
aws s3 ls "s3://hl-mainnet-node-data/explorer_blocks/0/100000000/" --request-payer requester | head -5

# 2024
aws s3 ls "s3://hl-mainnet-node-data/explorer_blocks/300000000/300000000/" --request-payer requester | head -5

# Recent
aws s3 ls "s3://hl-mainnet-node-data/explorer_blocks/700000000/700000000/" --request-payer requester | head -5

# Count files in a sample folder (extrapolate from there)
aws s3 ls "s3://hl-mainnet-node-data/explorer_blocks/0/0/" --request-payer requester | wc -l
```
