#!/usr/bin/env python3
"""Sum closed PnL for a user from Hyperliquid API."""

import requests
import sys

def get_user_fills_page(user_address: str, start_time: int = 0, end_time: int = None) -> list:
    """Fetch one page of fills for a user."""
    if end_time is None:
        end_time = int(1e15)

    resp = requests.post(
        "https://api.hyperliquid.xyz/info",
        json={
            "type": "userFillsByTime",
            "user": user_address,
            "startTime": start_time,
            "endTime": end_time,
            "aggregateByTime": False,
            "reversed": True,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()

def get_all_user_fills(user_address: str) -> list:
    """Fetch all fills for a user with pagination (max 10k available via API)."""
    all_fills = []
    end_time = None
    page = 1

    while True:
        fills = get_user_fills_page(user_address, start_time=0, end_time=end_time)
        if not fills:
            break

        print(f"  Page {page}: got {len(fills)} fills")
        all_fills.extend(fills)

        # API limit: only 10k most recent fills available
        if len(fills) < 2000:
            break

        # Use oldest fill's time - 1ms as new end_time for next page
        oldest_time = min(int(f["time"]) for f in fills)
        end_time = oldest_time - 1
        page += 1

    return all_fills

def sum_closed_pnl(fills: list) -> float:
    """Sum all closedPnl values from fills."""
    total = 0.0
    for fill in fills:
        if "closedPnl" in fill:
            total += float(fill["closedPnl"])
    return total

def main():
    user = sys.argv[1] if len(sys.argv) > 1 else "0x051315fb7c07702b5adfa0d897c080c11b8082dc"

    print(f"Fetching all fills for {user}...")
    fills = get_all_user_fills(user)
    print(f"Total: {len(fills)} fills")

    total_pnl = sum_closed_pnl(fills)
    print(f"Total closed PnL: ${total_pnl:,.2f}")

if __name__ == "__main__":
    main()
