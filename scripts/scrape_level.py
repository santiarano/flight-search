#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FlyLevel (LEVEL) price fetcher for SFO <-> BCN premium economy.
Uses FlyLevel's calendar API (no browser needed) via primp for TLS fingerprinting.

API endpoint: /nwe/flights/api/calendar/
Returns daily low-fare prices per month, one direction at a time.

Usage:
    python scrape_level.py                      # Fetch all available prices
    python scrape_level.py --merge MAIN.csv     # Merge into main search CSV
    python scrape_level.py --monitor             # Check if May-Jul dates opened
"""
import os as _os
_os.environ.setdefault("PYTHONIOENCODING", "utf-8")
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import primp
except ImportError:
    print("ERROR: primp not installed. Run: pip install primp", file=sys.stderr)
    sys.exit(1)

DEFAULT_CSV = os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-level.csv")
CALENDAR_API = "https://www.flylevel.com/nwe/flights/api/calendar/"

DEFAULT_OUTBOUND_START = "2026-04-21"
DEFAULT_OUTBOUND_END = "2026-05-11"
DEFAULT_MIN_DAYS = 60
DEFAULT_MAX_DAYS = 75


def parse_args():
    p = argparse.ArgumentParser(description="FlyLevel SFO<->BCN price fetcher")
    p.add_argument("--outbound-start", default=DEFAULT_OUTBOUND_START)
    p.add_argument("--outbound-end", default=DEFAULT_OUTBOUND_END)
    p.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS)
    p.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS)
    p.add_argument("--csv", default=DEFAULT_CSV, help="CSV output path")
    p.add_argument("--merge", default=None, help="Merge results into this CSV (main search CSV)")
    p.add_argument("--monitor", action="store_true", help="Just check if target dates have opened")
    p.add_argument("--currency", default="USD", choices=["USD", "EUR"])
    return p.parse_args()


def fetch_calendar(client, origin, dest, month, year, currency="USD"):
    """Fetch one month of calendar prices from FlyLevel API."""
    url = (
        f"{CALENDAR_API}?triptype=OW&origin={origin}&destination={dest}"
        f"&month={month:02d}&year={year}&currencyCode={currency}&originType=flights"
    )
    try:
        resp = client.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("dayPrices", [])
    except Exception as e:
        print(f"  API error {origin}->{dest} {year}-{month:02d}: {e}", file=sys.stderr)
    return []


def fetch_all_prices(client, origin, dest, months, currency="USD"):
    """Fetch prices across multiple months, deduplicate by date."""
    prices = {}
    for year, month in months:
        day_prices = fetch_calendar(client, origin, dest, month, year, currency)
        for dp in day_prices:
            date = dp.get("date")
            price = dp.get("price")
            if date and price is not None:
                # Keep cheapest if duplicate
                if date not in prices or price < prices[date]["price"]:
                    prices[date] = {
                        "date": date,
                        "price": price,
                        "group": dp.get("minimumPriceGroup"),
                        "tags": dp.get("tags"),
                    }
        time.sleep(1)  # Gentle rate limiting
    return prices


def build_combinations(outbound_prices, return_prices, min_days, max_days):
    """Build valid round-trip combinations."""
    results = []
    for out_date_str, out_data in outbound_prices.items():
        out_date = datetime.strptime(out_date_str, "%Y-%m-%d")
        for ret_date_str, ret_data in return_prices.items():
            ret_date = datetime.strptime(ret_date_str, "%Y-%m-%d")
            stay = (ret_date - out_date).days
            if stay < min_days or stay > max_days:
                continue

            total = out_data["price"] + ret_data["price"]
            results.append({
                "airline": "FlyLevel",
                "class": "premium-economy",
                "outbound_date": out_date_str,
                "return_date": ret_date_str,
                "stay_days": stay,
                "out_flight": "LEVEL",
                "out_departure": "",
                "out_arrival": "",
                "out_duration": "~11h (direct)",
                "out_stops": 0,
                "out_price": f"${out_data['price']}",
                "out_price_num": out_data["price"],
                "ret_flight": "LEVEL",
                "ret_departure": "",
                "ret_arrival": "",
                "ret_duration": "~12h (direct)",
                "ret_stops": 0,
                "ret_price": f"${ret_data['price']}",
                "ret_price_num": ret_data["price"],
                "total_price": f"${total:,.0f}",
                "total_price_num": total,
                "search_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    results.sort(key=lambda x: x["total_price_num"])
    return results


def write_csv(results, csv_path):
    """Write results to CSV."""
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    fields = [
        "airline", "class", "outbound_date", "return_date", "stay_days",
        "out_flight", "out_departure", "out_arrival", "out_duration", "out_stops", "out_price",
        "ret_flight", "ret_departure", "ret_arrival", "ret_duration", "ret_stops", "ret_price",
        "total_price", "search_date",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV written: {csv_path} ({len(results)} rows)")


def merge_into_main_csv(results, main_csv_path):
    """Append FlyLevel results to main search CSV, replacing old FlyLevel entries."""
    existing = []
    if os.path.exists(main_csv_path):
        with open(main_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            existing = [row for row in reader if row.get("airline") != "FlyLevel"]

    fields = [
        "airline", "class", "outbound_date", "return_date", "stay_days",
        "out_flight", "out_departure", "out_arrival", "out_duration", "out_stops", "out_price",
        "ret_flight", "ret_departure", "ret_arrival", "ret_duration", "ret_stops", "ret_price",
        "total_price", "search_date",
    ]

    all_rows = existing + [{k: str(v) for k, v in r.items() if k in fields} for r in results]

    with open(main_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Merged into: {main_csv_path} ({len(all_rows)} total rows, {len(results)} FlyLevel)")


def monitor_dates(client, target_months, currency="USD"):
    """Check if target months have prices (for monitoring when dates open)."""
    print("=== FlyLevel Date Availability Monitor ===\n")
    any_new = False

    for direction, origin, dest in [("Outbound", "SFO", "BCN"), ("Return", "BCN", "SFO")]:
        print(f"--- {direction}: {origin} -> {dest} ---")
        for year, month in target_months:
            prices = fetch_calendar(client, origin, dest, month, year, currency)
            with_price = [p for p in prices if p.get("price") is not None]
            if with_price:
                cheapest = min(with_price, key=lambda x: x["price"])
                print(f"  {year}-{month:02d}: {len(with_price)} dates available! Cheapest: ${cheapest['price']} on {cheapest['date']}")
                any_new = True
            else:
                print(f"  {year}-{month:02d}: not yet available")
            time.sleep(0.5)
        print()

    return any_new


def main():
    args = parse_args()
    client = primp.Client(impersonate="random")

    if args.monitor:
        # Check if May-Jul dates have opened
        target_months = [(2026, 5), (2026, 6), (2026, 7)]
        found = monitor_dates(client, target_months, args.currency)
        if found:
            print("NEW DATES AVAILABLE! Run without --monitor to fetch full prices.")
        else:
            print("Target dates (May-Jul 2026) not yet open for booking.")
            print("Current availability is through late April 2026 only.")
        return 0

    # Fetch all available prices
    print("=== FlyLevel Price Fetcher: SFO <-> BCN ===\n")

    # Determine which months to check based on date range
    out_start = datetime.strptime(args.outbound_start, "%Y-%m-%d")
    out_end = datetime.strptime(args.outbound_end, "%Y-%m-%d")

    # Build month list covering outbound and return periods
    outbound_months = set()
    current = out_start.replace(day=1)
    while current <= out_end:
        outbound_months.add((current.year, current.month))
        current = (current + timedelta(days=32)).replace(day=1)
    # Add month before for calendar overlap
    prev = out_start - timedelta(days=15)
    outbound_months.add((prev.year, prev.month))

    return_months = set()
    ret_start = out_start + timedelta(days=args.min_days)
    ret_end = out_end + timedelta(days=args.max_days)
    current = ret_start.replace(day=1)
    while current <= ret_end:
        return_months.add((current.year, current.month))
        current = (current + timedelta(days=32)).replace(day=1)

    print(f"Fetching outbound prices (SFO->BCN) for months: {sorted(outbound_months)}")
    outbound_prices = fetch_all_prices(client, "SFO", "BCN", sorted(outbound_months), args.currency)
    print(f"  Found {len(outbound_prices)} dates with prices")

    print(f"\nFetching return prices (BCN->SFO) for months: {sorted(return_months)}")
    return_prices = fetch_all_prices(client, "BCN", "SFO", sorted(return_months), args.currency)
    print(f"  Found {len(return_prices)} dates with prices")

    if not outbound_prices or not return_prices:
        print("\nNot enough price data for combinations.")
        print("FlyLevel likely hasn't opened May-Jul 2026 for booking yet.")
        print("\nAvailable outbound dates:")
        for d, p in sorted(outbound_prices.items()):
            print(f"  {d}: ${p['price']}")
        print("\nAvailable return dates:")
        for d, p in sorted(return_prices.items()):
            print(f"  {d}: ${p['price']}")

        # Still save what we have
        if outbound_prices:
            combos = build_combinations(outbound_prices, return_prices, 1, 999)
            if combos:
                write_csv(combos, args.csv)
                if args.merge:
                    merge_into_main_csv(combos, args.merge)
        return 0

    # Build combinations
    combos = build_combinations(outbound_prices, return_prices, args.min_days, args.max_days)
    print(f"\nValid {args.min_days}-{args.max_days} day combinations: {len(combos)}")

    if combos:
        write_csv(combos, args.csv)
        if args.merge:
            merge_into_main_csv(combos, args.merge)

        print(f"\n--- Top 10 Cheapest ---")
        for i, r in enumerate(combos[:10], 1):
            print(f"  {i}. {r['outbound_date']} -> {r['return_date']} ({r['stay_days']}d): {r['total_price']}")
    else:
        print("No valid combinations found within the stay range.")
        print("FlyLevel may not have opened the required return dates yet.")

    return 0


if __name__ == "__main__":
    main()
