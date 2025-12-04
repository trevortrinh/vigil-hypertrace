#!/usr/bin/env python3
"""
Find smart money traders who started trading after a cutoff date.

Usage:
    python find_new_smart_money.py                 # top 50 traders, Aug 1 cutoff
    python find_new_smart_money.py -n 100          # top 100 traders
    python find_new_smart_money.py -c 2025-10-01   # different cutoff
    python find_new_smart_money.py --all           # all traders
    python find_new_smart_money.py --lambda -w 10  # Lambda with 10 workers (parallel)
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv

load_dotenv()

LAMBDA_FUNCTION = "vigil-http-proxy"
LAMBDA_REGION = "us-east-1"
API_URL = "https://api.hyperliquid.xyz/info"


# -----------------------------------------------------------------------------
# HTTP Clients
# -----------------------------------------------------------------------------

class DirectClient:
    """Direct HTTP with rate limiting."""

    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.last = 0

    def post(self, payload: dict) -> dict:
        wait = self.delay - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()

        for attempt in range(3):
            resp = requests.post(API_URL, json=payload, timeout=30)
            if resp.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        raise Exception("Rate limited")


class LambdaClient:
    """Lambda HTTP client with IP rotation."""

    def __init__(self, workers: int = 5):
        import boto3
        self.client = boto3.client("lambda", region_name=LAMBDA_REGION)
        self.workers = workers

    def post(self, payload: dict) -> dict:
        for attempt in range(3):
            resp = self.client.invoke(
                FunctionName=LAMBDA_FUNCTION,
                InvocationType="RequestResponse",
                Payload=json.dumps({"url": API_URL, "method": "POST", "payload": payload}),
            )
            result = json.loads(resp["Payload"].read())
            if result.get("statusCode") == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            if result.get("statusCode") != 200:
                raise Exception(result.get("error", "Unknown error"))
            return json.loads(result["body"])
        raise Exception("Rate limited")

    def post_many(self, payloads: list[dict]) -> list:
        """Parallel requests."""
        results = [None] * len(payloads)
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = {ex.submit(self.post, p): i for i, p in enumerate(payloads)}
            for f in as_completed(futures):
                i = futures[f]
                try:
                    results[i] = f.result()
                except Exception as e:
                    results[i] = e
        return results


# -----------------------------------------------------------------------------
# API Helpers
# -----------------------------------------------------------------------------

def make_fills_payload(address: str, reversed: bool = False, start_time: int = 0) -> dict:
    """Build userFillsByTime payload."""
    return {
        "type": "userFillsByTime",
        "user": address,
        "startTime": start_time,
        "endTime": int(1e15),
        "aggregateByTime": False,
        "reversed": reversed,
    }


def get_trader_data_sequential(client, address: str, cutoff_ms: int, use_sleep: bool = True):
    """
    Get trader fill data with sequential API calls.
    For DirectClient (with rate limiting).

    Returns (is_new, first_fill, last_fill, api_pnl).
    """
    # Get oldest fills first (reversed=False)
    first_page = client.post(make_fills_payload(address, reversed=False))

    if not first_page:
        return False, None, None, None

    first_time = int(first_page[0]["time"])
    first_fill = datetime.fromtimestamp(first_time / 1000)
    is_new = first_time >= cutoff_ms

    if not is_new:
        # OLD trader - just get last fill
        last_page = client.post(make_fills_payload(address, reversed=True))
        last_fill = datetime.fromtimestamp(int(last_page[0]["time"]) / 1000)
        return False, first_fill, last_fill, None

    # NEW trader - get all fills for api_pnl
    all_fills = list(first_page)

    if len(first_page) == 2000:
        # Paginate forward
        start_time = max(int(f["time"]) for f in first_page) + 1
        while True:
            page = client.post(make_fills_payload(address, reversed=False, start_time=start_time))
            if not page:
                break
            all_fills.extend(page)
            if len(page) < 2000:
                break
            start_time = max(int(f["time"]) for f in page) + 1
            if use_sleep:
                time.sleep(0.3)

    last_fill = datetime.fromtimestamp(max(int(f["time"]) for f in all_fills) / 1000)
    api_pnl = sum(float(f.get("closedPnl", 0)) for f in all_fills)

    return True, first_fill, last_fill, api_pnl


# -----------------------------------------------------------------------------
# Main Processing
# -----------------------------------------------------------------------------

def get_traders(limit: int | None) -> list[dict]:
    """Fetch traders from DB ordered by Sharpe."""
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    query = """
        SELECT user_address, net_pnl, sharpe_ratio, win_rate, total_volume, trading_days
        FROM smart_money_watchlist ORDER BY sharpe_ratio DESC
    """
    if limit:
        query += f" LIMIT {limit}"
    with conn.cursor() as cur:
        cur.execute(query)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def make_record(trader: dict, is_new: bool, first, last, pnl) -> dict:
    """Build output record from trader data."""
    return {
        "address": trader["user_address"],
        "db_pnl": round(float(trader["net_pnl"]), 2),
        "sharpe": round(float(trader["sharpe_ratio"]), 2),
        "win_rate": round(float(trader["win_rate"]), 4),
        "volume": round(float(trader["total_volume"]), 2),
        "days": int(trader["trading_days"]),
        "is_new": is_new,
        "first_fill": str(first.date()) if first else None,
        "last_fill": str(last.date()) if last else None,
        "api_pnl": round(pnl, 2) if pnl else None,
    }


def process_sequential(client, traders: list[dict], cutoff_ms: int, output_file) -> int:
    """Process traders sequentially (for DirectClient)."""
    new_count = 0

    for i, trader in enumerate(traders, 1):
        addr = trader["user_address"]
        print(f"[{i}/{len(traders)}] {addr[:10]}...", end=" ", flush=True)

        try:
            is_new, first, last, pnl = get_trader_data_sequential(client, addr, cutoff_ms, use_sleep=True)

            if not first:
                print("no fills")
                record = make_record(trader, False, None, None, None)
            elif is_new:
                print(f"NEW {first.date()} -> {last.date()} ${pnl:,.0f}")
                record = make_record(trader, True, first, last, pnl)
                new_count += 1
            else:
                print(f"old ({first.date()} -> {last.date()})")
                record = make_record(trader, False, first, last, None)

        except Exception as e:
            print(f"error: {e}")
            record = {**make_record(trader, False, None, None, None), "error": str(e)}

        output_file.write(json.dumps(record) + "\n")
        output_file.flush()
        time.sleep(0.3)  # Rate limit for direct client

    return new_count


def process_batch_lambda(client: "LambdaClient", traders: list[dict], cutoff_ms: int, batch_start: int, total: int) -> list[dict]:
    """
    Process a batch of traders with parallel Lambda calls.
    Returns list of record dicts.
    """
    # Step 1: Parallel first-page queries (reversed=False to get oldest first)
    payloads = [make_fills_payload(t["user_address"], reversed=False) for t in traders]
    first_pages = client.post_many(payloads)

    results = []
    old_traders_needing_last = []  # (trader, first_fill, idx_in_batch)
    new_traders_needing_pagination = []  # (trader, first_page, first_fill, idx_in_batch)

    # Step 2: Categorize results
    for i, (trader, page) in enumerate(zip(traders, first_pages)):
        idx = batch_start + i + 1
        addr = trader["user_address"]

        if isinstance(page, Exception):
            print(f"[{idx}/{total}] {addr[:10]}... error: {page}")
            results.append({**make_record(trader, False, None, None, None), "error": str(page)})
            continue

        if not page:
            print(f"[{idx}/{total}] {addr[:10]}... no fills")
            results.append(make_record(trader, False, None, None, None))
            continue

        first_time = int(page[0]["time"])
        first_fill = datetime.fromtimestamp(first_time / 1000)
        is_new = first_time >= cutoff_ms

        if not is_new:
            # OLD trader - need to get last fill
            old_traders_needing_last.append((trader, first_fill, len(results)))
            results.append(None)  # Placeholder
        else:
            # NEW trader - may need pagination for PnL
            if len(page) < 2000:
                # All fills in one page
                last_fill = datetime.fromtimestamp(int(page[-1]["time"]) / 1000)
                api_pnl = sum(float(f.get("closedPnl", 0)) for f in page)
                print(f"[{idx}/{total}] {addr[:10]}... NEW {first_fill.date()} -> {last_fill.date()} ${api_pnl:,.0f}")
                results.append(make_record(trader, True, first_fill, last_fill, api_pnl))
            else:
                # Need pagination
                new_traders_needing_pagination.append((trader, page, first_fill, len(results)))
                results.append(None)  # Placeholder

    # Step 3: Batch get last fills for OLD traders
    if old_traders_needing_last:
        last_payloads = [make_fills_payload(t["user_address"], reversed=True) for t, _, _ in old_traders_needing_last]
        last_pages = client.post_many(last_payloads)

        for (trader, first_fill, result_idx), last_page in zip(old_traders_needing_last, last_pages):
            idx = batch_start + result_idx + 1
            addr = trader["user_address"]

            if isinstance(last_page, Exception):
                print(f"[{idx}/{total}] {addr[:10]}... error getting last: {last_page}")
                results[result_idx] = {**make_record(trader, False, first_fill, None, None), "error": str(last_page)}
            else:
                last_fill = datetime.fromtimestamp(int(last_page[0]["time"]) / 1000)
                print(f"[{idx}/{total}] {addr[:10]}... old ({first_fill.date()} -> {last_fill.date()})")
                results[result_idx] = make_record(trader, False, first_fill, last_fill, None)

    # Step 4: Handle NEW traders needing pagination (sequential per trader, but no sleeps)
    for trader, first_page, first_fill, result_idx in new_traders_needing_pagination:
        idx = batch_start + result_idx + 1
        addr = trader["user_address"]

        all_fills = list(first_page)
        start_time = max(int(f["time"]) for f in first_page) + 1

        while True:
            page = client.post(make_fills_payload(addr, reversed=False, start_time=start_time))
            if not page:
                break
            all_fills.extend(page)
            if len(page) < 2000:
                break
            start_time = max(int(f["time"]) for f in page) + 1

        last_fill = datetime.fromtimestamp(max(int(f["time"]) for f in all_fills) / 1000)
        api_pnl = sum(float(f.get("closedPnl", 0)) for f in all_fills)
        print(f"[{idx}/{total}] {addr[:10]}... NEW {first_fill.date()} -> {last_fill.date()} ${api_pnl:,.0f} ({len(all_fills)} fills)")
        results[result_idx] = make_record(trader, True, first_fill, last_fill, api_pnl)

    return results


def process_lambda(client: "LambdaClient", traders: list[dict], cutoff_ms: int, output_file) -> int:
    """Process traders with parallel Lambda calls."""
    new_count = 0
    batch_size = client.workers

    for i in range(0, len(traders), batch_size):
        batch = traders[i:i + batch_size]
        records = process_batch_lambda(client, batch, cutoff_ms, i, len(traders))

        for record in records:
            output_file.write(json.dumps(record) + "\n")
            output_file.flush()
            if record.get("is_new"):
                new_count += 1

    return new_count


def main():
    parser = argparse.ArgumentParser(description="Find new smart money traders")
    parser.add_argument("-n", "--limit", type=int, default=50)
    parser.add_argument("-c", "--cutoff", default="2025-08-01")
    parser.add_argument("-a", "--all", action="store_true")
    parser.add_argument("-o", "--output", type=str)
    parser.add_argument("-l", "--lambda", dest="use_lambda", action="store_true")
    parser.add_argument("-w", "--workers", type=int, default=5)
    args = parser.parse_args()

    cutoff = datetime.strptime(args.cutoff, "%Y-%m-%d")
    cutoff_ms = int(cutoff.timestamp() * 1000)
    limit = None if args.all else args.limit
    output = Path(args.output or f"data/new_smart_money_{cutoff:%Y%m%d}.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)

    client = LambdaClient(args.workers) if args.use_lambda else DirectClient()
    traders = get_traders(limit)

    print(f"Checking {len(traders)} traders (cutoff: {cutoff.date()})")
    print(f"Mode: {'Lambda (' + str(args.workers) + ' workers)' if args.use_lambda else 'Direct'}")
    print(f"Output: {output}\n")

    with open(output, "w") as f:
        if args.use_lambda:
            new_count = process_lambda(client, traders, cutoff_ms, f)
        else:
            new_count = process_sequential(client, traders, cutoff_ms, f)

    print(f"\nFound {new_count} new traders (of {len(traders)} checked) -> {output}")


if __name__ == "__main__":
    main()
