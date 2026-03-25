#!/usr/bin/env python3
"""
Google Flights Playwright scraper — emulates human search workflow.

Strategy:
1. Open calendar view to identify cheapest dates (including outside target range)
2. Search each date via direct URL to get accurate per-flight prices
3. Repeat for each direction × cabin class combo

Usage:
    python gf_scraper.py --headed                    # Watch the browser
    python gf_scraper.py                              # Headless
    python gf_scraper.py --report                     # Regenerate report from saved data
    python gf_scraper.py --dates 2026-04-23,2026-05-01  # Search specific dates only
"""
import sys, os, time, re, json, csv, random, argparse
from datetime import datetime, timedelta
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

# --- Config ---
SCRIPTS_DIR = Path(__file__).parent
DATA_DIR = SCRIPTS_DIR / "gf_data"
SHOTS_DIR = DATA_DIR / "screenshots"
CSV_PATH = Path(os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-search.csv"))
REPORT_PATH = Path(os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-report.html"))
RESULTS_FILE = DATA_DIR / "gf_results.json"

AIRLINE_PATTERN = re.compile(
    r"(United|TAP|Tap Air Portugal|LEVEL|Iberia|American|Delta|SWISS|"
    r"British Airways|Air France|KLM|Lufthansa|LOT|Aer Lingus|Finnair|Turkish|Norse)"
)


def parse_args():
    p = argparse.ArgumentParser(description="Google Flights Playwright scraper")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--report", action="store_true", help="Regenerate report only")
    p.add_argument("--dates", default=None, help="Comma-separated dates to search")
    p.add_argument("--direction", default="both", choices=["out", "ret", "both"])
    p.add_argument("--csv", default=str(CSV_PATH))
    p.add_argument("--html", default=str(REPORT_PATH))
    p.add_argument("--delay-min", type=float, default=5)
    p.add_argument("--delay-max", type=float, default=12)
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def setup():
    DATA_DIR.mkdir(exist_ok=True)
    SHOTS_DIR.mkdir(exist_ok=True)


def human_delay(lo=3, hi=7):
    time.sleep(random.uniform(lo, hi))


def click_el(page, locator):
    """Click by bounding box to bypass Material overlay interceptors."""
    el = locator.first
    box = el.bounding_box()
    if box and box["width"] > 0:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        return True
    return False


def create_browser(pw, headed):
    browser = pw.chromium.launch(
        headless=not headed,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/Los_Angeles",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    ctx.add_init_script(
        'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
    )
    return browser, ctx


# =============================================================================
# Calendar price extraction — identifies cheapest dates
# =============================================================================


def get_calendar_prices(page, origin, dest, cabin, debug=False):
    """
    Open Google Flights with route+class, click departure field to see calendar
    prices. Capture prices for all visible months.
    Returns: dict {date_str: price_int}
    """
    q = f"Flights from {origin} to {dest} one way {cabin} class"
    url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}"
    page.goto(url, timeout=30000)
    human_delay(4, 7)

    # Open date picker
    dep = page.locator('input[placeholder="Departure"]').first
    if not click_el(page, dep):
        print("  WARN: Could not open date picker")
        return {}
    human_delay(2, 4)

    MONTH_MAP = {
        "January": 1, "February": 2, "March": 3, "April": 4,
        "May": 5, "June": 6, "July": 7, "August": 8,
        "September": 9, "October": 10, "November": 11, "December": 12,
    }
    all_prices = {}

    # Navigate to April 2026 first
    for _ in range(20):
        body = page.inner_text("body")
        if "April 2026" in body:
            break
        next_btn = page.locator('button[aria-label="Next"]')
        if next_btn.count() > 0:
            click_el(page, next_btn)
            time.sleep(0.3)
        else:
            break

    # Wait for prices to load
    human_delay(6, 10)

    # Extract prices — aria-labels are on child divs inside gridcells
    # Structure: gridcell > div[role=button] > div[aria-label="Day, Month DD, YYYY"]
    #                                         > div (price text like "$3,504")
    def extract_visible_prices():
        labeled = page.locator('[role="gridcell"] [aria-label]').all()
        for el in labeled:
            label = el.get_attribute("aria-label") or ""
            dm = re.search(r"(\w+)\s+(\d{1,2}),\s+(\d{4})", label)
            if not dm:
                continue
            month_name, day, year = dm.group(1), int(dm.group(2)), int(dm.group(3))
            month_num = MONTH_MAP.get(month_name)
            if not month_num:
                continue
            date_str = f"{year}-{month_num:02d}-{day:02d}"

            # Price is in the sibling div or in the parent's text
            parent = el.locator("..").first
            text = parent.inner_text().strip()
            pm = re.search(r"\$([\d,]+)", text)
            if pm:
                price = int(pm.group(1).replace(",", ""))
                all_prices[date_str] = price

    extract_visible_prices()

    # Navigate forward month by month to cover May, June, July
    for _ in range(6):
        next_btn = page.locator('button[aria-label="Next"]')
        if next_btn.count() > 0:
            click_el(page, next_btn)
            human_delay(2, 4)  # Wait for prices to load
            extract_visible_prices()
        body = page.inner_text("body")
        if "August 2026" in body:
            break

    if debug:
        page.screenshot(path=str(SHOTS_DIR / "calendar_final.png"))

    # Close date picker
    page.keyboard.press("Escape")
    human_delay(0.5, 1)

    return all_prices


# =============================================================================
# Per-date search — accurate flight prices
# =============================================================================


def search_date(page, origin, dest, date_str, cabin, delay_range=(5, 12), debug=False):
    """
    Search flights for one date via direct URL.
    Returns list of flight dicts.
    """
    q = f"Flights from {origin} to {dest} on {date_str} one way {cabin} class"
    url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}"
    page.goto(url, timeout=30000)
    human_delay(5, 9)

    # Scroll down to load all results
    page.mouse.wheel(0, 500)
    human_delay(1, 2)

    # Click "Show more" if present
    try:
        more = page.locator('button:has-text("more flights"), button:has-text("Show more")')
        if more.count() > 0:
            click_el(page, more)
            human_delay(2, 4)
    except:
        pass

    if debug:
        page.screenshot(path=str(SHOTS_DIR / f"search_{date_str}.png"))

    # Extract flights from li elements
    flights = []
    items = page.locator("li").all()
    for item in items:
        text = item.inner_text().strip()
        if not re.search(r"\$[\d,]+", text):
            continue
        if len(text) < 30 or len(text) > 600:
            continue
        airlines = AIRLINE_PATTERN.findall(text)
        if not airlines:
            continue

        price_m = re.search(r"\$([\d,]+)", text)
        price = int(price_m.group(1).replace(",", "")) if price_m else 0
        if price < 50 or price > 50000:
            continue

        times = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)", text)
        dur = re.search(r"(\d+)\s*hr\s*(?:(\d+)\s*min)?", text)
        dur_str = dur.group() if dur else ""

        if "Nonstop" in text or "nonstop" in text:
            stops = 0
        else:
            sm = re.search(r"(\d+)\s*stop", text)
            stops = int(sm.group(1)) if sm else -1

        airline = airlines[0]
        # Normalize airline names
        if airline in ("TAP", "Tap Air Portugal"):
            airline = "TAP Portugal"

        flights.append({
            "airline": airline,
            "price": price,
            "departure": times[0] if times else "",
            "arrival": times[1] if len(times) > 1 else "",
            "duration": dur_str,
            "stops": stops,
        })

    # Deduplicate
    seen = set()
    unique = []
    for f in flights:
        key = (f["airline"], f["price"], f["departure"])
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return unique


# =============================================================================
# Main orchestration
# =============================================================================


def identify_dates_to_search(calendar_prices, target_start, target_end, extra_buffer=7, top_n=25):
    """
    From calendar prices, pick the dates to search in detail:
    - All dates in target range
    - Plus cheapest dates slightly outside range (for reference)
    """
    target_dates = set()
    reference_dates = set()

    start = datetime.strptime(target_start, "%Y-%m-%d")
    end = datetime.strptime(target_end, "%Y-%m-%d")
    buffer_start = start - timedelta(days=extra_buffer)
    buffer_end = end + timedelta(days=extra_buffer)

    for date_str, price in sorted(calendar_prices.items(), key=lambda x: x[1]):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if start <= dt <= end:
            target_dates.add(date_str)
        elif buffer_start <= dt <= buffer_end:
            reference_dates.add(date_str)

    # If too many, keep cheapest
    all_dates = sorted(target_dates | reference_dates,
                       key=lambda d: calendar_prices.get(d, 99999))
    return all_dates[:top_n], target_dates, reference_dates


def run_search(args):
    """Run the full search pipeline."""
    setup()

    # Search configs
    searches = [
        {
            "name": "Business (United/TAP)",
            "cabin": "business",
            "airlines_of_interest": {"United", "TAP Portugal", "Tap Air Portugal"},
            "out_range": ("2026-04-15", "2026-05-15"),
            "ret_range": ("2026-06-25", "2026-07-25"),
        },
        {
            "name": "Premium Economy (LEVEL)",
            "cabin": "premium economy",
            "airlines_of_interest": {"LEVEL", "Iberia"},
            "out_range": ("2026-04-15", "2026-05-15"),
            "ret_range": ("2026-06-25", "2026-07-25"),
            # Note: If LEVEL doesn't appear in premium economy search,
            # also try economy (LEVEL only has one cabin but GF may classify differently)
            "fallback_cabin": "economy",
        },
    ]

    all_outbound = {}  # date -> [flights]
    all_return = {}
    all_cal_out = {}
    all_cal_ret = {}

    with sync_playwright() as pw:
        browser, ctx = create_browser(pw, args.headed)
        page = ctx.new_page()

        for search in searches:
            cabin = search["cabin"]
            print(f"\n{'#'*60}")
            print(f"# {search['name']}")
            print(f"{'#'*60}")

            # --- Outbound calendar ---
            if args.direction in ("out", "both"):
                print(f"\n--- Outbound calendar: SFO→BCN ({cabin}) ---")
                cal_out = get_calendar_prices(page, "SFO", "BCN", cabin, args.debug)
                all_cal_out.update(cal_out)
                print(f"  Calendar prices: {len(cal_out)} dates")

                # Identify dates to search
                if args.dates:
                    out_dates = args.dates.split(",")
                else:
                    out_start, out_end = search["out_range"]
                    out_dates, _, _ = identify_dates_to_search(
                        cal_out, out_start, out_end, extra_buffer=7, top_n=20
                    )
                    if not out_dates:
                        # Fallback: sample every 3 days in range
                        d = datetime.strptime(out_start, "%Y-%m-%d")
                        end = datetime.strptime(out_end, "%Y-%m-%d")
                        out_dates = []
                        while d <= end:
                            out_dates.append(d.strftime("%Y-%m-%d"))
                            d += timedelta(days=3)

                # Print cheapest from calendar
                if cal_out:
                    print("  Cheapest calendar dates:")
                    for d, pr in sorted(cal_out.items(), key=lambda x: x[1])[:10]:
                        print(f"    {d}: ${pr:,}")

                # Search each date
                print(f"\n  Searching {len(out_dates)} outbound dates...")
                for i, date_str in enumerate(out_dates):
                    print(f"  [{i+1}/{len(out_dates)}] {date_str}...", end=" ", flush=True)
                    flights = search_date(page, "SFO", "BCN", date_str, cabin,
                                         (args.delay_min, args.delay_max), args.debug)

                    # If this config has a fallback cabin and we got 0 target airlines,
                    # retry with fallback (e.g. LEVEL shows in economy, not premium economy)
                    interesting = [f for f in flights if f["airline"] in search["airlines_of_interest"]]
                    if not interesting and search.get("fallback_cabin"):
                        fb = search["fallback_cabin"]
                        print(f"(retrying as {fb})...", end=" ", flush=True)
                        human_delay(2, 4)
                        fb_flights = search_date(page, "SFO", "BCN", date_str, fb,
                                                 (args.delay_min, args.delay_max), args.debug)
                        # Only keep target airlines from fallback, mark as premium-economy
                        for f in fb_flights:
                            if f["airline"] in search["airlines_of_interest"]:
                                f["class_override"] = "premium-economy"
                                flights.append(f)
                        interesting = [f for f in flights if f["airline"] in search["airlines_of_interest"]]

                    print(f"{len(flights)} total, {len(interesting)} target airlines")
                    for f in interesting[:3]:
                        print(f"    {f['airline']}: ${f['price']:,} ({f['duration']}, {f['stops']} stops)")

                    all_outbound.setdefault(date_str, []).extend(flights)
                    human_delay(args.delay_min, args.delay_max)

                    # Longer pause every 8 searches
                    if (i + 1) % 8 == 0:
                        print("  (longer pause)")
                        human_delay(15, 30)

            # --- Return calendar ---
            if args.direction in ("ret", "both"):
                print(f"\n--- Return calendar: BCN→SFO ({cabin}) ---")
                cal_ret = get_calendar_prices(page, "BCN", "SFO", cabin, args.debug)
                all_cal_ret.update(cal_ret)
                print(f"  Calendar prices: {len(cal_ret)} dates")

                if args.dates:
                    ret_dates = args.dates.split(",")
                else:
                    ret_start, ret_end = search["ret_range"]
                    ret_dates, _, _ = identify_dates_to_search(
                        cal_ret, ret_start, ret_end, extra_buffer=7, top_n=20
                    )
                    if not ret_dates:
                        d = datetime.strptime(ret_start, "%Y-%m-%d")
                        end = datetime.strptime(ret_end, "%Y-%m-%d")
                        ret_dates = []
                        while d <= end:
                            ret_dates.append(d.strftime("%Y-%m-%d"))
                            d += timedelta(days=3)

                if cal_ret:
                    print("  Cheapest calendar dates:")
                    for d, pr in sorted(cal_ret.items(), key=lambda x: x[1])[:10]:
                        print(f"    {d}: ${pr:,}")

                print(f"\n  Searching {len(ret_dates)} return dates...")
                for i, date_str in enumerate(ret_dates):
                    print(f"  [{i+1}/{len(ret_dates)}] {date_str}...", end=" ", flush=True)
                    flights = search_date(page, "BCN", "SFO", date_str, cabin,
                                         (args.delay_min, args.delay_max), args.debug)

                    interesting = [f for f in flights if f["airline"] in search["airlines_of_interest"]]
                    if not interesting and search.get("fallback_cabin"):
                        fb = search["fallback_cabin"]
                        print(f"(retrying as {fb})...", end=" ", flush=True)
                        human_delay(2, 4)
                        fb_flights = search_date(page, "BCN", "SFO", date_str, fb,
                                                 (args.delay_min, args.delay_max), args.debug)
                        for f in fb_flights:
                            if f["airline"] in search["airlines_of_interest"]:
                                f["class_override"] = "premium-economy"
                                flights.append(f)
                        interesting = [f for f in flights if f["airline"] in search["airlines_of_interest"]]

                    print(f"{len(flights)} total, {len(interesting)} target airlines")
                    for f in interesting[:3]:
                        print(f"    {f['airline']}: ${f['price']:,} ({f['duration']}, {f['stops']} stops)")

                    all_return.setdefault(date_str, []).extend(flights)
                    human_delay(args.delay_min, args.delay_max)

                    if (i + 1) % 8 == 0:
                        print("  (longer pause)")
                        human_delay(15, 30)

        browser.close()

    # Save raw results
    save_data = {
        "outbound": {d: fs for d, fs in all_outbound.items()},
        "return": {d: fs for d, fs in all_return.items()},
        "calendar_outbound": all_cal_out,
        "calendar_return": all_cal_ret,
        "timestamp": datetime.now().isoformat(),
    }
    RESULTS_FILE.write_text(json.dumps(save_data, indent=2, default=str))
    print(f"\nRaw data saved: {RESULTS_FILE}")

    # Build combinations and output
    generate_output(save_data, args)


def generate_output(data, args):
    """Build combinations, write CSV, generate report."""
    combos = []
    out = data.get("outbound", {})
    ret = data.get("return", {})

    for out_date, out_flights in out.items():
        out_dt = datetime.strptime(out_date, "%Y-%m-%d")
        for ret_date, ret_flights in ret.items():
            ret_dt = datetime.strptime(ret_date, "%Y-%m-%d")
            stay = (ret_dt - out_dt).days
            if stay < 55 or stay > 80:  # Wider than strict 60-75 for reference
                continue

            # Best per airline for outbound
            for of in out_flights:
                for rf in ret_flights:
                    total = of["price"] + rf["price"]
                    cabin = of.get("class_override", "business")

                    # Airline label
                    if of["airline"] == rf["airline"]:
                        label = of["airline"]
                    else:
                        label = f"{of['airline']} + {rf['airline']}"

                    combos.append({
                        "airline": label,
                        "class": cabin,
                        "outbound_date": out_date,
                        "return_date": ret_date,
                        "stay_days": stay,
                        "out_flight": of["airline"],
                        "out_departure": of.get("departure", ""),
                        "out_arrival": of.get("arrival", ""),
                        "out_duration": of.get("duration", ""),
                        "out_stops": of.get("stops", ""),
                        "out_price": f"${of['price']:,}",
                        "out_price_num": of["price"],
                        "ret_flight": rf["airline"],
                        "ret_departure": rf.get("departure", ""),
                        "ret_arrival": rf.get("arrival", ""),
                        "ret_duration": rf.get("duration", ""),
                        "ret_stops": rf.get("stops", ""),
                        "ret_price": f"${rf['price']:,}",
                        "ret_price_num": rf["price"],
                        "total_price": f"${total:,}",
                        "total_price_num": total,
                        "search_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })

    # Keep best per (out_date, ret_date, airline_label) to reduce duplicates
    best = {}
    for c in combos:
        key = (c["outbound_date"], c["return_date"], c["airline"])
        if key not in best or c["total_price_num"] < best[key]["total_price_num"]:
            best[key] = c

    combos = sorted(best.values(), key=lambda x: x["total_price_num"])
    print(f"\nTotal unique combinations: {len(combos)}")

    # Write CSV
    csv_path = args.csv
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
        writer.writerows(combos)
    print(f"CSV: {csv_path} ({len(combos)} rows)")

    # Generate HTML report
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from generate_report import generate_report
        generate_report(csv_path, args.html)
    except Exception as e:
        print(f"Report generation failed: {e}")

    # Summary
    if combos:
        print(f"\n{'='*60}")
        print(f"TOP 15 CHEAPEST")
        print(f"{'='*60}")
        for i, c in enumerate(combos[:15], 1):
            flag = " *REF*" if c["stay_days"] < 60 or c["stay_days"] > 75 else ""
            print(f"  {i:2d}. {c['airline']:<25s} {c['total_price']:>8s}  "
                  f"{c['outbound_date']}→{c['return_date']} ({c['stay_days']}d){flag}")

    # Calendar cheapest
    cal_out = data.get("calendar_outbound", {})
    cal_ret = data.get("calendar_return", {})
    if cal_out:
        print(f"\n--- Cheapest outbound dates (calendar) ---")
        for d, pr in sorted(cal_out.items(), key=lambda x: x[1])[:10]:
            print(f"  {d}: ${pr:,}")
    if cal_ret:
        print(f"\n--- Cheapest return dates (calendar) ---")
        for d, pr in sorted(cal_ret.items(), key=lambda x: x[1])[:10]:
            print(f"  {d}: ${pr:,}")


def main():
    args = parse_args()

    if args.report:
        if not RESULTS_FILE.exists():
            print("No saved data. Run a search first.")
            return
        data = json.loads(RESULTS_FILE.read_text())
        generate_output(data, args)
        return

    run_search(args)


if __name__ == "__main__":
    main()
