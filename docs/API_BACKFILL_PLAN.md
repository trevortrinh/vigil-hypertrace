# Hyperliquid API Backfill Integration Plan

## Goal
Backfill pre-Jul 2025 fills for all users (~100k+) via Hyperliquid API into TimescaleDB.

## Overview
- **API Endpoint:** `POST https://api.hyperliquid.xyz/info` with `{"type": "userFillsByTime", ...}`
- **Limits:** 10k fills max per user, 2k per request, 500 element pagination
- **Rate Limit:** 1200 weight/minute (~40 requests/min conservative)

## Files to Create

### 1. `src/vigil/api.py` - API Client

```python
"""Hyperliquid API client for fetching user fills."""

import time
from typing import Iterator
import requests

HL_API_URL = "https://api.hyperliquid.xyz/info"
MAX_FILLS_PER_REQUEST = 2000
MAX_FILLS_PER_USER = 10000

class RateLimiter:
    """Simple rate limiter."""
    def __init__(self, requests_per_minute: int = 40):
        self.min_interval = 60.0 / requests_per_minute
        self.last_request = 0.0

    def wait(self):
        elapsed = time.time() - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()

class HyperliquidAPI:
    """Client for Hyperliquid info API."""

    def __init__(self, requests_per_minute: int = 40):
        self.session = requests.Session()
        self.rate_limiter = RateLimiter(requests_per_minute)

    def get_user_fills_by_time(self, user: str, start_time: int, end_time: int | None = None) -> list[dict]:
        """Fetch fills for a user within a time range (up to 2000)."""
        self.rate_limiter.wait()
        payload = {"type": "userFillsByTime", "user": user, "startTime": start_time}
        if end_time:
            payload["endTime"] = end_time
        response = self.session.post(HL_API_URL, json=payload)
        response.raise_for_status()
        return response.json()

    def iter_user_fills(self, user: str, start_time: int, end_time: int) -> Iterator[list[dict]]:
        """Iterate all fills for a user, paginating backward by time."""
        current_end = end_time
        total = 0

        while total < MAX_FILLS_PER_USER:
            fills = self.get_user_fills_by_time(user, start_time, current_end)
            if not fills:
                break
            yield fills
            total += len(fills)

            oldest = min(f["time"] for f in fills)
            if oldest <= start_time or len(fills) < MAX_FILLS_PER_REQUEST:
                break
            current_end = oldest - 1
```

### 2. `sql/003_backfill_progress.sql` - Progress Tracking

```sql
CREATE TABLE IF NOT EXISTS backfill_progress (
    user_address     TEXT PRIMARY KEY,
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    completed        BOOLEAN DEFAULT false,
    fills_count      INT DEFAULT 0,
    oldest_fill_time BIGINT
);

CREATE INDEX IF NOT EXISTS idx_backfill_completed ON backfill_progress (completed);

-- Prevent duplicate fills
CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_tid_unique ON fills (tid);
```

### 3. `scripts/backfill_users.py` - Backfill Script

```python
#!/usr/bin/env python3
"""Backfill historical user fills from Hyperliquid API."""

from datetime import datetime
import polars as pl
from tqdm import tqdm
from vigil.api import HyperliquidAPI
from vigil.db import get_db_connection, load_dataframe_to_db

S3_START_MS = int(datetime(2025, 7, 27).timestamp() * 1000)
HL_LAUNCH_MS = int(datetime(2023, 11, 1).timestamp() * 1000)

def get_users_to_backfill(conn) -> list[str]:
    """Get users not yet backfilled."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT user_address FROM fills
            WHERE user_address NOT IN (
                SELECT user_address FROM backfill_progress WHERE completed = true
            )
        """)
        return [row[0] for row in cur.fetchall()]

def backfill_user(api, conn, user: str) -> int:
    """Backfill one user, return fills count."""
    total = 0
    for fills in api.iter_user_fills(user, HL_LAUNCH_MS, S3_START_MS - 1):
        for f in fills:
            f["user"] = user
            f.setdefault("block_time", None)
        df = pl.DataFrame(fills, infer_schema_length=None)
        total += load_dataframe_to_db(df, conn)
        conn.commit()
    return total

def main():
    with get_db_connection() as conn:
        users = get_users_to_backfill(conn)
        api = HyperliquidAPI(requests_per_minute=40)

        for user in tqdm(users, desc="Backfilling"):
            # Mark started, backfill, mark completed
            ...
```

## Key Implementation Details

### Column Mapping
API uses same camelCase as S3 - reuses existing `PARQUET_TO_DB` mapping in `db.py`.

**Missing fields from API:**
- `user` - must add manually from request
- `block_time` - set to NULL

### Deduplication
Add unique index on `tid` to prevent duplicates if script restarts or API/S3 data overlaps.

### Parallel Execution (Multiple IPs)

Run from multiple machines, each with its own IP for independent rate limits.

**Worker sharding approach:**
```bash
# Machine 1
python scripts/backfill_users.py --worker-id 0 --total-workers 4

# Machine 2
python scripts/backfill_users.py --worker-id 1 --total-workers 4

# etc...
```

**Sharding logic in script:**
```python
def get_users_to_backfill(conn, worker_id: int, total_workers: int) -> list[str]:
    """Get users for this worker (deterministic hash-based sharding)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT user_address FROM fills
            WHERE user_address NOT IN (
                SELECT user_address FROM backfill_progress WHERE completed = true
            )
            AND MOD(ABS(HASHTEXT(user_address)), %s) = %s
            ORDER BY user_address
        """, (total_workers, worker_id))
        return [row[0] for row in cur.fetchall()]
```

**Time with parallelization:**
| Workers | Time (avg scenario) |
|---------|---------------------|
| 1 | ~125 hours |
| 4 | ~31 hours |
| 10 | ~12 hours |

### Time Estimates (100k users, single worker)
| Scenario | Requests | Time |
|----------|----------|------|
| Optimistic (1 req/user) | 100k | ~42 hours |
| Average (3 req/user) | 300k | ~125 hours |
| Pessimistic (5 req/user) | 500k | ~208 hours |

## Files to Modify

| File | Change |
|------|--------|
| `src/vigil/__init__.py` | Export `HyperliquidAPI` |
| `src/vigil/config.py` | Add `HL_API_URL`, `HL_API_REQUESTS_PER_MINUTE` |
| `.env.example` | Add `HL_API_REQUESTS_PER_MINUTE=40` |

## Execution Steps

1. Run `sql/003_backfill_progress.sql` migration
2. Create `src/vigil/api.py`
3. Create `scripts/backfill_users.py`
4. Test with `--limit 5` on small sample
5. Run full backfill (or parallel from multiple IPs)
