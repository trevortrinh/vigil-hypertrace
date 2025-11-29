# Reconstructing Hyperliquid Fills (Feb 2023 - Mar 2025)

## The Problem

```
Available in S3:
├── explorer_blocks    → Orders (inputs)      ✓ Feb 2023+
├── node_fills         → Fills (outputs)      ✓ May 2025+ only
└── state_snapshots    → Positions            ✗ Not public

Gap: ~2 years of fills not archived (Feb 2023 - Mar 2025)
```

The matching engine computed fills from day 1, but outputs weren't archived until 2025.

---

## Reconstruction Options

### Option 1: Request from Hyperliquid

**Best case scenario** - they have the data.

Ask them to release:
- Historical `node_fills` exports
- Periodic state snapshots
- Or backfill via API (remove 10k limit)

**Likelihood**: Unknown. Worth asking.

---

### Option 2: API Backfill (Partial)

**What's available:**
```python
POST https://api.hyperliquid.xyz/info
{
  "type": "userFillsByTime",
  "user": "0x...",
  "startTime": 0  # from beginning
}
# Returns up to 10,000 most recent fills
```

**Coverage:**
- ~99% of traders have <10k lifetime fills → complete history
- ~1% (~4,000 traders) have >10k fills → truncated history

**Process:**
1. Get all addresses from explorer_blocks
2. Call API for each address
3. Store fills
4. Flag addresses with exactly 10k fills (likely truncated)

**Effort**: Low (days)
**Completeness**: ~95% of fills, 99% of traders

---

### Option 3: Build Matching Engine Replica

**The hard but complete solution.**

Since matching is deterministic:
```
Same orders + Same sequence = Same fills
```

We have all orders in `explorer_blocks`. We can replay.

#### Core Matching Logic

```python
class OrderBook:
    def __init__(self):
        self.bids = SortedDict()  # price -> [orders] (descending)
        self.asks = SortedDict()  # price -> [orders] (ascending)
        self.orders = {}          # oid -> order

class MatchingEngine:
    def __init__(self):
        self.books = {}  # asset_id -> OrderBook
        self.fills = []

    def process_order(self, order, user, timestamp):
        book = self.books[order['a']]

        # Determine order type
        tif = order['t']['limit']['tif']
        side = 'buy' if order['b'] else 'sell'
        price = Decimal(order['p'])
        size = Decimal(order['s'])
        reduce_only = order['r']

        if tif == 'Alo':  # Add Liquidity Only (maker only)
            if self._would_cross(side, price, book):
                return  # Rejected, no fill
            self._add_to_book(order, user, book)

        elif tif == 'Ioc':  # Immediate or Cancel
            self._match(side, price, size, user, book, timestamp)
            # Any unfilled portion is cancelled

        elif tif == 'Gtc':  # Good til Cancel
            remaining = self._match(side, price, size, user, book, timestamp)
            if remaining > 0:
                self._add_to_book(order, user, book, remaining)

    def _would_cross(self, side, price, book):
        if side == 'buy' and book.asks:
            return price >= book.asks.peekitem(0)[0]
        if side == 'sell' and book.bids:
            return price <= book.bids.peekitem(-1)[0]
        return False

    def _match(self, side, price, size, user, book, timestamp):
        remaining = size
        opposite = book.asks if side == 'buy' else book.bids

        while remaining > 0 and opposite:
            best_price, orders = opposite.peekitem(0 if side == 'buy' else -1)

            # Check if price crosses
            if side == 'buy' and price < best_price:
                break
            if side == 'sell' and price > best_price:
                break

            for resting_order in orders[:]:
                fill_size = min(remaining, resting_order['remaining'])

                fill = {
                    'time': timestamp,
                    'asset': order['a'],
                    'price': best_price,  # Price improvement
                    'size': fill_size,
                    'buyer': user if side == 'buy' else resting_order['user'],
                    'seller': resting_order['user'] if side == 'buy' else user,
                    'taker': user,
                    'maker': resting_order['user']
                }
                self.fills.append(fill)

                remaining -= fill_size
                resting_order['remaining'] -= fill_size

                if resting_order['remaining'] == 0:
                    orders.remove(resting_order)
                    del self.orders[resting_order['oid']]

                if remaining == 0:
                    break

            if not orders:
                del opposite[best_price]

        return remaining

    def process_cancel(self, cancel):
        oid = cancel['o']
        if oid in self.orders:
            order = self.orders[oid]
            # Remove from book
            del self.orders[oid]
```

#### Additional Complexity

| Feature | Implementation Needed |
|---------|----------------------|
| Price-time priority | Orders at same price matched by arrival time |
| Partial fills | Track remaining size per order |
| Reduce-only | Check position before allowing fill |
| Self-trade prevention | Reject if maker == taker |
| Trigger orders | Stop loss, take profit - trigger on price |
| Liquidations | Forced closes at liquidation price |
| Funding payments | Periodic funding between longs/shorts |
| Position limits | Max position size checks |
| Tick size | Price rounding rules per asset |
| Lot size | Size rounding rules per asset |

#### Validation Strategy

```python
# 1. Replay from genesis
fills_reconstructed = replay_all_blocks(explorer_blocks)

# 2. Compare against known data (May 2025+)
fills_actual = load_node_fills(start='2025-05')

# 3. Validate match rate
for fill in fills_actual:
    if fill not in fills_reconstructed:
        print(f"Missing fill: {fill}")

# 4. Tune matching logic until >99.9% match
```

**Effort**: 2-4 weeks
**Completeness**: 100% (if done correctly)
**Risk**: Edge cases in matching logic

---

### Option 4: Hybrid Approach (Recommended)

Combine methods for best coverage with least effort:

```
Step 1: API Backfill (days)
├── Get all addresses from explorer_blocks
├── Call userFillsByTime for each
├── Store results
└── Identify truncated addresses (exactly 10k fills)

Step 2: Analyze Gaps (hours)
├── How many addresses truncated? (~4,000)
├── How many fills missing? (estimate)
├── Is full reconstruction worth it?

Step 3: Targeted Reconstruction (if needed)
├── Only replay blocks where truncated addresses traded
├── Only need matching logic for those time periods
└── Much smaller scope than full replay
```

---

## Data Requirements

### For API Backfill

```python
# 1. Extract addresses from explorer_blocks
addresses = set()
for block_file in glob('explorer_blocks/**/*.rmp.lz4'):
    for block in parse_blocks(block_file):
        for tx in block['txs']:
            addresses.add(tx['user'])

# Estimated: 100k-500k unique addresses

# 2. Rate-limited API calls
for addr in addresses:
    fills = api.userFillsByTime(user=addr, startTime=0)
    save(addr, fills)
    time.sleep(0.1)  # Rate limit

# Time estimate: 500k addresses * 0.1s = 14 hours
```

### For Full Reconstruction

```
Download: ~3-4 TB (explorer_blocks)
Storage: ~15 TB (decompressed + working data)
Compute: Process 800M blocks
Memory: Order book state (~10-100 GB depending on history depth)
Time: Days to weeks depending on implementation
```

---

## Recommended Approach

```
Phase 1: Quick wins (1-2 days)
├── Download node_fills (May 2025+) - complete data
├── Extract all addresses from recent explorer_blocks sample
└── Estimate total address count

Phase 2: API backfill (1-2 days)
├── Get all addresses from explorer_blocks
├── Backfill via API (10k limit)
├── Identify truncated traders
└── Assess gap size

Phase 3: Decision point
├── If gap is acceptable → Done
├── If gap matters → Build reconstruction
└── If Hyperliquid releases data → Use that

Phase 4: Reconstruction (if needed, 2-4 weeks)
├── Build matching engine
├── Validate against 2025 data
├── Replay historical blocks
└── Merge with API data
```

---

## Estimated Coverage by Approach

| Approach | Traders Covered | Fills Covered | Effort |
|----------|----------------|---------------|--------|
| node_fills only | 100% (May 2025+) | 100% (May 2025+) | 1 day |
| + API backfill | 100% | ~95% | 3 days |
| + Targeted replay | 100% | ~99% | 1-2 weeks |
| + Full replay | 100% | 100% | 3-4 weeks |

---

## Code: Address Extraction

```python
import msgpack
import lz4.frame
from pathlib import Path

def extract_all_addresses(explorer_blocks_dir):
    """Extract all unique addresses from explorer_blocks"""
    addresses = set()

    for lz4_file in Path(explorer_blocks_dir).rglob('*.rmp.lz4'):
        with open(lz4_file, 'rb') as f:
            decompressed = lz4.frame.decompress(f.read())
            blocks = msgpack.unpackb(decompressed, raw=False)

        for block in blocks:
            for tx in block.get('txs', []):
                user = tx.get('user')
                if user:
                    addresses.add(user)

    return addresses

def backfill_fills_from_api(addresses, output_dir):
    """Backfill fills for all addresses via API"""
    import requests
    import json
    import time

    truncated = []

    for i, addr in enumerate(addresses):
        resp = requests.post(
            'https://api.hyperliquid.xyz/info',
            json={'type': 'userFillsByTime', 'user': addr, 'startTime': 0}
        )
        fills = resp.json()

        # Save
        with open(f'{output_dir}/{addr}.json', 'w') as f:
            json.dump(fills, f)

        # Check if truncated
        if len(fills) == 10000:
            truncated.append(addr)

        # Rate limit
        if i % 100 == 0:
            print(f'Processed {i}/{len(addresses)}')
        time.sleep(0.05)

    return truncated
```

---

## Summary

**The fills exist** - Hyperliquid computed them. They're just not public.

**Best path forward:**
1. Ask Hyperliquid for historical data
2. If no: API backfill covers 95%+ of fills
3. If 100% needed: Build matching engine (2-4 weeks)

**Key insight:** Matching is deterministic. Given all orders (which we have), fills can be reconstructed. It's engineering effort, not impossible.
