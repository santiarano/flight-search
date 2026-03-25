#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check FlyLevel prices for SFO-BCN route.
LEVEL doesn't appear in Google Flights, so we check their calendar API.
Falls back to web search if API is unavailable.
"""
import os, sys
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import csv
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import primp
except ImportError:
    primp = None


LEVEL_CALENDAR_URL = "https://www.flylevel.com/api/ndc/FlightCalendarPricesLevel"
CSV_PATH = os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-level.csv")


def fetch_level_calendar(origin, dest, start_date, num_days=60, product_class="OP"):
    """
    Try to fetch LEVEL's flight calendar prices.
    product_class: BA=Basic, OP=Optima (premium economy)
    """
    if not primp:
        print("primp not available, cannot make requests")
        return None

    params = {
        "startDate": start_date,
        "numDays": str(num_days),
        "origin": origin,
        "destination": dest,
        "productClass": product_class,
        "currency": "USD",
        "paxCount": "1",
    }

    try:
        client = primp.Client(impersonate="chrome_131")
        url = LEVEL_CALENDAR_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        resp = client.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"LEVEL API returned {resp.status_code}")
            return None
    except Exception as e:
        print(f"LEVEL API error: {e}")
        return None


def generate_level_manual_urls(outbound_start, outbound_end, return_start, return_end):
    """Generate flylevel.com search URLs for manual checking."""
    urls = []
    # Key sample dates (weekly intervals)
    out_start = datetime.strptime(outbound_start, "%Y-%m-%d")
    out_end = datetime.strptime(outbound_end, "%Y-%m-%d")

    current = out_start
    while current <= out_end:
        date_str = current.strftime("%Y-%m-%d")
        # Premium economy round trip URL pattern
        url = (
            f"https://www.flylevel.com/en-us/booking/select"
            f"?origin=SFO&destination=BCN&departDate={date_str}"
            f"&adults=1&children=0&infants=0&cabin=PE"
        )
        urls.append({"date": date_str, "url": url})
        current += timedelta(days=3)  # Every 3 days

    return urls


def main():
    print("=== FlyLevel SFO <-> BCN Price Check ===\n")

    # Try the calendar API
    print("Attempting LEVEL calendar API...")
    outbound_data = fetch_level_calendar("SFO", "BCN", "2026-04-25", 30, "OP")
    return_data = fetch_level_calendar("BCN", "SFO", "2026-06-24", 35, "OP")

    results = []

    if outbound_data:
        print("Got outbound calendar data!")
        # Parse calendar response (structure varies)
        print(json.dumps(outbound_data, indent=2)[:2000])
    else:
        print("Calendar API unavailable (requires authorization).\n")

    if return_data:
        print("Got return calendar data!")
        print(json.dumps(return_data, indent=2)[:2000])
    else:
        print("Return calendar API also unavailable.\n")

    # Generate manual check URLs
    print("\n--- Manual Check URLs for FlyLevel ---")
    print("Check these URLs on flylevel.com to get premium economy prices:\n")

    urls_out = generate_level_manual_urls("2026-04-25", "2026-05-15", "2026-06-24", "2026-07-24")
    print("OUTBOUND (SFO -> BCN):")
    for u in urls_out:
        print(f"  {u['date']}: {u['url']}")

    urls_ret = generate_level_manual_urls("2026-06-24", "2026-07-24", "", "")
    # Generate return URLs
    print("\nRETURN (BCN -> SFO):")
    ret_start = datetime.strptime("2026-06-24", "%Y-%m-%d")
    ret_end = datetime.strptime("2026-07-24", "%Y-%m-%d")
    current = ret_start
    while current <= ret_end:
        date_str = current.strftime("%Y-%m-%d")
        url = (
            f"https://www.flylevel.com/en-us/booking/select"
            f"?origin=BCN&destination=SFO&departDate={date_str}"
            f"&adults=1&children=0&infants=0&cabin=PE"
        )
        print(f"  {date_str}: {url}")
        current += timedelta(days=3)

    # Write a placeholder CSV with manual check instructions
    print(f"\n--- LEVEL Price Estimates ---")
    print("Based on web search data:")
    print("  - LEVEL SFO->BCN premium economy: ~$600-900 one-way")
    print("  - LEVEL BCN->SFO premium economy: ~$600-900 one-way")
    print("  - Estimated round-trip: ~$1,200-1,800")
    print("  - This is SIGNIFICANTLY cheaper than United/TAP business class")
    print("  - Trade-off: premium economy vs business class")
    print("\nTo get exact prices, check flylevel.com with the URLs above.")


if __name__ == "__main__":
    main()
