# Hyperliquid Historical Data Research

## Key Finding: FULL HISTORY EXISTS

The `explorer_blocks` S3 bucket contains **complete blockchain history from genesis (February 26, 2023)**.

## S3 Buckets Overview

| Bucket | Content | Date Range | Format |
|--------|---------|------------|--------|
| `s3://hl-mainnet-node-data/explorer_blocks/` | **Full block data with all txs** | Feb 2023 - Present | `.rmp.lz4` (MessagePack + LZ4) |
| `s3://hl-mainnet-node-data/replica_cmds/` | Raw blockchain commands | Jan 2025 - Present | Various |
| `s3://hl-mainnet-node-data/node_trades/hourly/` | Parsed trade data | Mar 22, 2025 - Present | Hourly files |
| `s3://hl-mainnet-node-data/node_fills/hourly/` | Parsed fill data | May 25, 2025 - Present | Hourly files |
| `s3://hl-mainnet-node-data/node_fills_by_block/hourly/` | Fills organized by block | Jul 27, 2025 - Present | Hourly files |
| `s3://hyperliquid-archive/market_data/` | L2 book snapshots | Apr 15, 2023 - Present | `.lz4` |
| `s3://hl-mainnet-evm-blocks/` | HyperEVM blocks | Block 0 - Present | Various |

## explorer_blocks Structure

```
s3://hl-mainnet-node-data/explorer_blocks/
├── 0/                          # Blocks 0-99,999,999
│   ├── 0/                      # Blocks 0-99,999
│   │   ├── 1000.rmp.lz4       # Blocks 901-1000
│   │   ├── 1100.rmp.lz4       # Blocks 1001-1100
│   │   └── ...
│   ├── 100000/                 # Blocks 100,000-199,999
│   └── ...
├── 100000000/                  # Blocks 100M-199M
│   ├── 100000000/
│   │   ├── 100000100.rmp.lz4  # Blocks 100,000,001-100,000,100
│   │   └── ...
└── ...
```

Files are batched in groups of 100 blocks, labeled by ending block number.

## Block Data Schema

Each `.rmp.lz4` file contains an array of blocks:

```json
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
      "actions": [...]
    }
  ]
}
```

## Action Types Found

### 1. `order` - Place Order
```json
{
  "type": "order",
  "orders": [{
    "a": 59,           // asset ID
    "b": true,         // true=buy, false=sell
    "p": "0.20294",    // price
    "s": "7475",       // size
    "r": false,        // reduce only
    "t": {
      "limit": {"tif": "Ioc"}  // order type
    }
  }],
  "grouping": "na"
}
```

### 2. `cancel` - Cancel Order
```json
{
  "type": "cancel",
  "cancels": [{
    "a": 9,            // asset ID
    "o": 3018048517    // order ID
  }]
}
```

### 3. `SetGlobalAction` - Oracle Price Updates
```json
{
  "type": "SetGlobalAction",
  "pxs": [["36902.0", "36936.0"], ...]  // bid/ask per asset
}
```

### 4. `connect` - Agent Wallet Connection
```json
{
  "type": "connect",
  "chain": "Arbitrum",
  "agent": ["https://hyperliquid.xyz", "0x..."],
  "agentAddress": "0x..."
}
```

## How to Download

```bash
# Set AWS profile
export AWS_PROFILE=trevor

# List available blocks
aws s3 ls s3://hl-mainnet-node-data/explorer_blocks/ --request-payer requester

# Download specific block range
aws s3 cp "s3://hl-mainnet-node-data/explorer_blocks/0/0/1000.rmp.lz4" . --request-payer requester

# Decompress
unlz4 1000.rmp.lz4 1000.rmp

# Parse with Python
python3 -c "
import msgpack
with open('1000.rmp', 'rb') as f:
    data = msgpack.unpack(f, raw=False)
print(data)
"
```

## Tracking Traders: What's Possible

### From explorer_blocks (Feb 2023 - Present)
- **Every order placed** with user address
- **Every cancellation** with user address
- **Every agent wallet connection**
- **All oracle price updates**

### What's NOT directly in explorer_blocks
- **Fills/Trades** - Need to infer from order matching or use node_trades/fills
- **Positions** - Need to reconstruct from order flow
- **PnL** - Need to calculate from fills + prices

### Reconstruction Strategy

1. **Extract all orders from explorer_blocks** (genesis to present)
2. **Build order book state** per block
3. **Match crossing orders** to identify fills
4. **Track position changes** per user
5. **Cross-reference with node_trades** (Mar 2025+) for validation

## Data Gaps Analysis

| Period | Orders | Fills | Notes |
|--------|--------|-------|-------|
| Feb 2023 - Mar 2025 | ✅ explorer_blocks | ❌ Must reconstruct | ~2 years of data |
| Mar 2025 - May 2025 | ✅ explorer_blocks | ✅ node_trades | Early format |
| May 2025 - Jul 2025 | ✅ explorer_blocks | ✅ node_fills | Enhanced with PnL |
| Jul 2025 - Present | ✅ explorer_blocks | ✅ node_fills_by_block | Current format |

## Key Insight

**The blockchain data DOES exist and is publicly accessible via S3.**

The previous research was misleading because:
1. The "easy" parsed trade data (node_fills) only started in 2025
2. But the raw blockchain data (explorer_blocks) has been available since genesis
3. You just need to parse and reconstruct fills from the order flow

## Sample Files Downloaded

- `1000.rmp.lz4` - Earliest blocks (Feb 26, 2023)
- `100000100.rmp.lz4` - Block 100M (Nov 13, 2023) - has 13,608 orders in 100 blocks

## Key Insight: Orders vs Fills

**explorer_blocks contains ORDERS, not FILLS**

- Orders are what users submit
- Fills are when orders match
- To get fills from pre-2025, you'd need to:
  1. Replay the order book from orders
  2. Match crossing orders to identify fills
  3. OR use API `userFills` (limited to 10k per address)

**The good news**: All user addresses ARE in explorer_blocks from genesis, even without reconstructing fills.

## Next Steps

1. Build a parser for explorer_blocks to extract all user addresses
2. Get unique addresses from order/cancel actions
3. Use API `userFillsByTime` to backfill fills for each address (up to 10k most recent)
4. For high-volume traders (>10k fills pre-2025), would need to reconstruct from order matching
5. Validate against node_fills data for 2025+

## Sample Python Code

```python
import msgpack
import lz4.frame
from collections import defaultdict

def extract_addresses_from_blocks(rmp_file):
    """Extract all unique addresses from a block file"""
    with open(rmp_file, 'rb') as f:
        data = msgpack.unpack(f, raw=False)

    addresses = set()
    for block in data:
        for tx in block.get('txs', []):
            user = tx.get('user')
            if user:
                addresses.add(user)

    return addresses

def count_activity_by_address(rmp_file):
    """Count orders and cancels per address"""
    with open(rmp_file, 'rb') as f:
        data = msgpack.unpack(f, raw=False)

    activity = defaultdict(lambda: {'orders': 0, 'cancels': 0})

    for block in data:
        for tx in block.get('txs', []):
            user = tx.get('user')
            if not user:
                continue
            for action in tx.get('actions', []):
                if action.get('type') == 'order':
                    activity[user]['orders'] += len(action.get('orders', []))
                elif action.get('type') == 'cancel':
                    activity[user]['cancels'] += len(action.get('cancels', []))

    return dict(activity)
```

## Estimated Data Size

Based on block 100M sample (Nov 2023):
- 100 blocks = ~600KB compressed, ~2.4MB uncompressed
- ~13,600 orders per 100 blocks
- ~800M blocks total as of Nov 2025 = ~4.8TB uncompressed (rough estimate)

Full download would be expensive and time-consuming. Better approach:
1. Download recent data (2025+) which has parsed fills
2. For historical addresses, use API to backfill what's available
3. Only download full block history if you need complete order book reconstruction
