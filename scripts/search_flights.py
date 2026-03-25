#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os as _os
_os.environ.setdefault("PYTHONIOENCODING", "utf-8")
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")

"""
Flight search script for SFO -> BCN route.
Searches Google Flights via fast-flights for all date combinations.
Outputs CSV and optionally updates Google Sheets via gog CLI.

Usage:
    python search_flights.py [--outbound-start 2026-04-25] [--outbound-end 2026-05-15]
                             [--min-days 60] [--max-days 70]
                             [--sheet-id SPREADSHEET_ID] [--csv flights.csv]
                             [--airlines united,tap,level] [--seat business]
                             [--max-stops 1] [--top N]
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    from fast_flights import FlightData, Passengers, get_flights
except ImportError:
    print("ERROR: fast-flights not installed. Run: pip install fast-flights", file=sys.stderr)
    sys.exit(1)


# --- Configuration ---
AIRLINES_CONFIG = {
    "united": {"name": "United", "seat": "business", "keywords": ["United"]},
    "tap": {"name": "TAP Portugal", "seat": "business", "keywords": ["TAP"]},
    "level": {"name": "FlyLevel", "seat": "premium-economy", "keywords": ["LEVEL", "Level", "Fly Level", "FlyLevel"]},
}

DEFAULT_OUTBOUND_START = "2026-04-21"
DEFAULT_OUTBOUND_END = "2026-05-11"
DEFAULT_MIN_DAYS = 60
DEFAULT_MAX_DAYS = 75
DEFAULT_FROM = "SFO"
DEFAULT_TO = "BCN"
DEFAULT_CSV = os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-search.csv")
GOG_ACCOUNT = "santiarano@gmail.com"


def parse_args():
    p = argparse.ArgumentParser(description="Flight search SFO→BCN")
    p.add_argument("--outbound-start", default=DEFAULT_OUTBOUND_START)
    p.add_argument("--outbound-end", default=DEFAULT_OUTBOUND_END)
    p.add_argument("--min-days", type=int, default=DEFAULT_MIN_DAYS)
    p.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS)
    p.add_argument("--from-airport", default=DEFAULT_FROM)
    p.add_argument("--to-airport", default=DEFAULT_TO)
    p.add_argument("--airlines", default="united,tap,level", help="Comma-separated airline keys")
    p.add_argument("--max-stops", type=int, default=1)
    p.add_argument("--sheet-id", default=None, help="Google Sheet ID to update")
    p.add_argument("--csv", default=DEFAULT_CSV, help="CSV output path")
    p.add_argument("--top", type=int, default=0, help="Only show top N cheapest results")
    p.add_argument("--delay", type=float, default=2.0, help="Delay between API calls (seconds)")
    p.add_argument("--quick", action="store_true", help="Quick mode: sample every 3rd date combo")
    p.add_argument("--mix-airlines", action="store_true", help="Include cross-airline combos (e.g. United out, TAP return)")
    p.add_argument("--html", default=None, help="Generate HTML report at this path")
    return p.parse_args()


def generate_date_combinations(outbound_start, outbound_end, min_days, max_days):
    """Generate all (outbound_date, return_date) pairs."""
    combos = []
    start = datetime.strptime(outbound_start, "%Y-%m-%d")
    end = datetime.strptime(outbound_end, "%Y-%m-%d")
    current = start
    while current <= end:
        for stay in range(min_days, max_days + 1):
            ret = current + timedelta(days=stay)
            combos.append((current.strftime("%Y-%m-%d"), ret.strftime("%Y-%m-%d")))
        current += timedelta(days=1)
    return combos


def extract_price(price_str):
    """Extract numeric price from string like '$5,741'."""
    if not price_str:
        return float("inf")
    cleaned = price_str.replace("$", "").replace(",", "").replace("€", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return float("inf")


def search_one_leg(date, from_apt, to_apt, seat, max_stops, airline_keywords=None, retries=2):
    """Search flights for one leg (one direction, one date). Retries on failure."""
    for attempt in range(retries + 1):
        try:
            result = get_flights(
                flight_data=[FlightData(date=date, from_airport=from_apt, to_airport=to_apt)],
                trip="one-way",
                seat=seat,
                passengers=Passengers(adults=1),
                max_stops=max_stops,
            )
            flights = []
            for f in result.flights:
                name = f.name if hasattr(f, "name") else ""
                # Filter by airline if specified
                if airline_keywords:
                    if not any(kw.lower() in name.lower() for kw in airline_keywords):
                        continue
                flights.append({
                    "airline": name,
                    "departure": f.departure if hasattr(f, "departure") else "",
                    "arrival": f.arrival if hasattr(f, "arrival") else "",
                    "duration": f.duration if hasattr(f, "duration") else "",
                    "stops": f.stops if hasattr(f, "stops") else "",
                    "price": f.price if hasattr(f, "price") else "",
                    "price_num": extract_price(f.price if hasattr(f, "price") else ""),
                })
            return flights
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            err_msg = str(e)[:200] if len(str(e)) > 200 else str(e)
            print(f"  WARN: no results {from_apt}->{to_apt} {date} ({seat}): {err_msg}", file=sys.stderr)
            return []


def search_all_combinations(args):
    """Run the full search across all date combos and airlines."""
    combos = generate_date_combinations(
        args.outbound_start, args.outbound_end, args.min_days, args.max_days
    )
    airlines = [a.strip() for a in args.airlines.split(",")]

    print(f"\n=== Flight Search: {args.from_airport} ↔ {args.to_airport} ===")
    print(f"Outbound range: {args.outbound_start} to {args.outbound_end}")
    print(f"Stay: {args.min_days}-{args.max_days} days")
    print(f"Airlines: {', '.join(airlines)}")
    print(f"Date combinations: {len(combos)}")

    if args.quick:
        combos = combos[::3]
        print(f"Quick mode: sampling {len(combos)} combinations")

    # We need to search outbound and return legs separately
    # First, collect unique outbound dates and return dates
    outbound_dates = sorted(set(c[0] for c in combos))
    return_dates = sorted(set(c[1] for c in combos))

    print(f"Unique outbound dates: {len(outbound_dates)}")
    print(f"Unique return dates: {len(return_dates)}")

    # Cache: search each unique date once per airline/seat combo
    outbound_cache = {}  # (date, airline_key) -> [flights]
    return_cache = {}    # (date, airline_key) -> [flights]

    total_searches = (len(outbound_dates) + len(return_dates)) * len(airlines)
    search_num = 0

    for airline_key in airlines:
        config = AIRLINES_CONFIG.get(airline_key)
        if not config:
            print(f"WARNING: Unknown airline key '{airline_key}', skipping", file=sys.stderr)
            continue

        seat = config["seat"]
        keywords = config["keywords"]

        print(f"\n--- Searching {config['name']} ({seat}) ---")

        # Search outbound dates
        for date in outbound_dates:
            search_num += 1
            print(f"  [{search_num}/{total_searches}] Outbound {date} ...", end=" ", flush=True)
            flights = search_one_leg(date, args.from_airport, args.to_airport, seat, args.max_stops, keywords)
            outbound_cache[(date, airline_key)] = flights
            print(f"{len(flights)} flights")
            time.sleep(args.delay)

        # Search return dates
        for date in return_dates:
            search_num += 1
            print(f"  [{search_num}/{total_searches}] Return {date} ...", end=" ", flush=True)
            flights = search_one_leg(date, args.to_airport, args.from_airport, seat, args.max_stops, keywords)
            return_cache[(date, airline_key)] = flights
            print(f"{len(flights)} flights")
            time.sleep(args.delay)

    # Build airline pair list: same-airline combos, plus cross-airline if --mix-airlines
    airline_pairs = [(a, a) for a in airlines]
    if args.mix_airlines:
        for a1 in airlines:
            for a2 in airlines:
                if a1 != a2 and (a1, a2) not in airline_pairs:
                    airline_pairs.append((a1, a2))

    # Now combine: for each (outbound_date, return_date, airline_pair), find best outbound + best return
    results = []
    for out_date, ret_date in combos:
        stay_days = (datetime.strptime(ret_date, "%Y-%m-%d") - datetime.strptime(out_date, "%Y-%m-%d")).days
        for out_airline_key, ret_airline_key in airline_pairs:
            out_config = AIRLINES_CONFIG.get(out_airline_key)
            ret_config = AIRLINES_CONFIG.get(ret_airline_key)
            if not out_config or not ret_config:
                continue

            out_flights = outbound_cache.get((out_date, out_airline_key), [])
            ret_flights = return_cache.get((ret_date, ret_airline_key), [])

            if not out_flights or not ret_flights:
                continue

            # Get cheapest outbound and return
            best_out = min(out_flights, key=lambda x: x["price_num"])
            best_ret = min(ret_flights, key=lambda x: x["price_num"])

            total_price = best_out["price_num"] + best_ret["price_num"]
            if total_price >= float("inf"):
                continue

            # Label: same airline or "AirlineA + AirlineB"
            if out_airline_key == ret_airline_key:
                label = out_config["name"]
                cabin = out_config["seat"]
            else:
                label = f"{out_config['name']} + {ret_config['name']}"
                cabin = f"{out_config['seat']} / {ret_config['seat']}"

            results.append({
                "airline": label,
                "class": cabin,
                "outbound_date": out_date,
                "return_date": ret_date,
                "stay_days": stay_days,
                "out_flight": best_out["airline"],
                "out_departure": best_out["departure"],
                "out_arrival": best_out["arrival"],
                "out_duration": best_out["duration"],
                "out_stops": best_out["stops"],
                "out_price": best_out["price"],
                "out_price_num": best_out["price_num"],
                "ret_flight": best_ret["airline"],
                "ret_departure": best_ret["departure"],
                "ret_arrival": best_ret["arrival"],
                "ret_duration": best_ret["duration"],
                "ret_stops": best_ret["stops"],
                "ret_price": best_ret["price"],
                "ret_price_num": best_ret["price_num"],
                "total_price": f"${total_price:,.0f}",
                "total_price_num": total_price,
                "search_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    # Sort by total price
    results.sort(key=lambda x: x["total_price_num"])

    if args.top > 0:
        results = results[:args.top]

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

    print(f"\nCSV written: {csv_path} ({len(results)} rows)")
    return csv_path


def update_google_sheet(results, sheet_id):
    """Update Google Sheet via gog CLI."""
    if not sheet_id:
        return None

    # Clear existing data (keep header)
    try:
        subprocess.run(
            ["gog", "sheets", "clear", sheet_id, "Search!A2:Z",
             f"--account={GOG_ACCOUNT}", "--no-input"],
            capture_output=True, text=True, timeout=30
        )
    except Exception:
        pass

    # Prepare header
    header = [
        "Airline", "Class", "Outbound Date", "Return Date", "Stay (days)",
        "Out Flight", "Out Departure", "Out Arrival", "Out Duration", "Out Stops", "Out Price",
        "Ret Flight", "Ret Departure", "Ret Arrival", "Ret Duration", "Ret Stops", "Ret Price",
        "Total Price", "Search Date",
    ]

    # Prepare rows
    rows = [header]
    for r in results:
        rows.append([
            r["airline"], r["class"], r["outbound_date"], r["return_date"], str(r["stay_days"]),
            r["out_flight"], r["out_departure"], r["out_arrival"], r["out_duration"],
            str(r["out_stops"]), r["out_price"],
            r["ret_flight"], r["ret_departure"], r["ret_arrival"], r["ret_duration"],
            str(r["ret_stops"]), r["ret_price"],
            r["total_price"], r["search_date"],
        ])

    values_json = json.dumps(rows)

    try:
        result = subprocess.run(
            ["gog", "sheets", "update", sheet_id, "Search!A1",
             "--values-json", values_json,
             "--input", "USER_ENTERED",
             f"--account={GOG_ACCOUNT}", "--no-input"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            print(f"\nGoogle Sheet updated: https://docs.google.com/spreadsheets/d/{sheet_id}")
            return True
        else:
            print(f"WARNING: Sheet update failed: {result.stderr}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"WARNING: Sheet update error: {e}", file=sys.stderr)
        return False


def create_google_sheet(title="SFO↔BCN Flight Search"):
    """Create a new Google Sheet and return its ID."""
    try:
        result = subprocess.run(
            ["gog", "sheets", "create", title,
             f"--account={GOG_ACCOUNT}", "--no-input", "--json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            sheet_id = data.get("spreadsheetId") or data.get("id")
            if sheet_id:
                print(f"Created new sheet: https://docs.google.com/spreadsheets/d/{sheet_id}")
                return sheet_id
    except Exception as e:
        print(f"WARNING: Could not create sheet: {e}", file=sys.stderr)
    return None


def print_summary(results):
    """Print a summary of the top results."""
    if not results:
        print("\nNo results found!")
        return

    print(f"\n{'='*80}")
    print(f"TOP 20 CHEAPEST FLIGHTS (of {len(results)} total)")
    print(f"{'='*80}")
    print(f"{'#':>3} {'Airline':<15} {'Class':<16} {'Out Date':<12} {'Ret Date':<12} {'Days':>4} {'Out Price':>10} {'Ret Price':>10} {'TOTAL':>10}")
    print(f"{'-'*3} {'-'*15} {'-'*16} {'-'*12} {'-'*12} {'-'*4} {'-'*10} {'-'*10} {'-'*10}")

    for i, r in enumerate(results[:20], 1):
        print(f"{i:>3} {r['airline']:<15} {r['class']:<16} {r['outbound_date']:<12} {r['return_date']:<12} {r['stay_days']:>4} {r['out_price']:>10} {r['ret_price']:>10} {r['total_price']:>10}")

    # Summary by airline
    print(f"\n--- Best by airline ---")
    seen = set()
    for r in results:
        if r["airline"] not in seen:
            seen.add(r["airline"])
            print(f"  {r['airline']}: {r['total_price']} ({r['outbound_date']} → {r['return_date']}, {r['stay_days']} days)")


def main():
    args = parse_args()
    results = search_all_combinations(args)

    # Write CSV
    csv_path = write_csv(results, args.csv)

    # Update or create Google Sheet
    sheet_id = args.sheet_id
    if not sheet_id:
        sheet_id = create_google_sheet()
    if sheet_id:
        update_google_sheet(results, sheet_id)

    # Generate HTML report if requested
    if args.html:
        try:
            from generate_report import generate_report
            generate_report(csv_path, args.html)
        except Exception as e:
            print(f"WARNING: HTML report generation failed: {e}", file=sys.stderr)

    # Print summary
    print_summary(results)

    # Save sheet ID for future runs
    state_file = Path(__file__).parent / ".flight-search-state.json"
    state = {}
    if state_file.exists():
        state = json.loads(state_file.read_text())
    state["sheet_id"] = sheet_id
    state["last_run"] = datetime.now().isoformat()
    state["total_results"] = len(results)
    state_file.write_text(json.dumps(state, indent=2))

    return 0


if __name__ == "__main__":
    main()
