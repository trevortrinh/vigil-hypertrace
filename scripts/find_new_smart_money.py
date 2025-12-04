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
        for attempt in range(6):
            resp = self.client.invoke(
                FunctionName=LAMBDA_FUNCTION,
                InvocationType="RequestResponse",
                Payload=json.dumps({"url": API_URL, "method": "POST", "payload": payload}),
            )
            result = json.loads(resp["Payload"].read())
            if result.get("statusCode") == 429:
                wait = min(2 ** (attempt + 1), 30)
                print(f" [429, wait {wait}s]", end="", flush=True)
                time.sleep(wait)
                continue
            if result.get("statusCode") != 200:
                raise Exception(result.get("error", "Unknown error"))
            return json.loads(result["body"])
        raise Exception("Rate limited after 6 retries")

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
# Helpers
# -----------------------------------------------------------------------------

def make_fills_payload(address: str) -> dict:
    """Build userFillsByTime payload - oldest first, just need 1 fill."""
    return {
        "type": "userFillsByTime",
        "user": address,
        "startTime": 0,
        "endTime": int(1e15),
        "aggregateByTime": False,
        "reversed": False,  # Oldest first
    }


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


def make_record(trader: dict, is_new: bool, error=None) -> dict:
    """Build output record."""
    rec = {
        "address": trader["user_address"],
        "is_new": is_new,
        "db_pnl": round(float(trader["net_pnl"]), 2),
        "sharpe": round(float(trader["sharpe_ratio"]), 2),
        "win_rate": round(float(trader["win_rate"]), 4),
        "volume": round(float(trader["total_volume"]), 2),
        "days": int(trader["trading_days"]),
    }
    if error:
        rec["error"] = str(error)
    return rec


# -----------------------------------------------------------------------------
# Processing
# -----------------------------------------------------------------------------

def process_sequential(client, traders: list[dict], cutoff_ms: int, output_file) -> int:
    """Process traders sequentially (for DirectClient)."""
    new_count = 0

    for i, trader in enumerate(traders, 1):
        addr = trader["user_address"]
        print(f"[{i}/{len(traders)}] {addr[:10]}...", end=" ", flush=True)

        try:
            page = client.post(make_fills_payload(addr))

            if not page:
                print("no fills")
                record = make_record(trader, False)
            else:
                first_time = int(page[0]["time"])
                is_new = first_time >= cutoff_ms
                print("NEW" if is_new else "old")
                record = make_record(trader, is_new)
                if is_new:
                    new_count += 1

        except Exception as e:
            print(f"error: {e}")
            record = make_record(trader, False, error=e)

        output_file.write(json.dumps(record) + "\n")
        output_file.flush()
        time.sleep(0.3)

    return new_count


def process_lambda(client: "LambdaClient", traders: list[dict], cutoff_ms: int, output_file) -> int:
    """Process traders with parallel Lambda calls."""
    new_count = 0
    batch_size = client.workers

    for i in range(0, len(traders), batch_size):
        batch = traders[i:i + batch_size]

        # Parallel first-page queries - 1 API call per trader!
        payloads = [make_fills_payload(t["user_address"]) for t in batch]
        pages = client.post_many(payloads)

        for j, (trader, page) in enumerate(zip(batch, pages)):
            idx = i + j + 1
            addr = trader["user_address"]

            if isinstance(page, Exception):
                print(f"[{idx}/{len(traders)}] {addr[:10]}... error: {page}")
                record = make_record(trader, False, error=page)
            elif not page:
                print(f"[{idx}/{len(traders)}] {addr[:10]}... no fills")
                record = make_record(trader, False)
            else:
                first_time = int(page[0]["time"])
                is_new = first_time >= cutoff_ms
                print(f"[{idx}/{len(traders)}] {addr[:10]}... {'NEW' if is_new else 'old'}")
                record = make_record(trader, is_new)
                if is_new:
                    new_count += 1

            output_file.write(json.dumps(record) + "\n")
            output_file.flush()

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
