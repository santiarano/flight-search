#!/usr/bin/env python3
"""
Google Flights smart round-trip scraper.
Emulates human workflow: pick cheapest outbound from calendar,
then pick cheapest return from the updated return calendar.

Workflow:
1. Open GF, round-trip, business, SFO→BCN
2. Open departure calendar → extract all date prices
3. Pick top N cheapest outbound dates
4. For each: click date → return calendar updates → extract return prices
5. Pick cheapest return → record total RT price
6. Also record 2nd, 3rd cheapest returns
7. Repeat for premium economy / LEVEL

Usage:
    python gf_smart.py --headed
    python gf_smart.py --headed --cabin "premium economy"
"""
import sys, os, time, re, json, csv, random, argparse
from datetime import datetime, timedelta
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

SCRIPTS_DIR = Path(__file__).parent
DATA_DIR = SCRIPTS_DIR / "gf_data"
CSV_PATH = Path(os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-roundtrip.csv"))
REPORT_PATH = Path(os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-report.html"))

MONTH_MAP = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}

AIRLINE_PATTERN = re.compile(
    r"(United(?:Lufthansa)?|United|TAP|Tap Air Portugal|LEVEL|Iberia|American|Delta|"
    r"SWISS|British Airways|Air France|KLM|Lufthansa)"
)


def parse_args():
    p = argparse.ArgumentParser(description="Google Flights smart RT scraper")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--cabin", default="business")
    p.add_argument("--top-outbound", type=int, default=12, help="How many cheapest outbound dates to explore")
    p.add_argument("--top-return", type=int, default=5, help="How many return options to record per outbound")
    p.add_argument("--airlines", default="United,TAP,LEVEL,Iberia,Lufthansa")
    p.add_argument("--csv", default=str(CSV_PATH))
    p.add_argument("--html", default=str(REPORT_PATH))
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def human_delay(lo=2, hi=5):
    time.sleep(random.uniform(lo, hi))


def click_el(page, locator):
    el = locator.first
    box = el.bounding_box()
    if box and box["width"] > 0:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        return True
    return False


def extract_calendar_prices(page, target_months=None):
    """
    Extract prices from the currently visible calendar in the date picker.
    Looks at aria-label on child divs of gridcells to get dates,
    and sibling text for prices.
    Returns: dict {date_str: price_int}
    """
    prices = {}

    # Find all elements with date aria-labels inside gridcells
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

        # Check if this date is in our target window
        if target_months:
            if (year, month_num) not in target_months:
                continue

        # Price is in sibling/parent text
        try:
            parent = el.locator("..").first
            text = parent.inner_text().strip()
        except:
            text = ""
        pm = re.search(r"\$([\d,]+)", text)
        if pm:
            price = int(pm.group(1).replace(",", ""))
            prices[date_str] = price

    return prices


def navigate_calendar_to(page, target_year, target_month):
    """Navigate the open calendar to show the target month."""
    for _ in range(20):
        body = page.inner_text("body")
        month_name = datetime(target_year, target_month, 1).strftime("%B")
        if f"{month_name} {target_year}" in body:
            return True
        next_btn = page.locator('button[aria-label="Next"]')
        if next_btn.count() > 0:
            click_el(page, next_btn)
            time.sleep(0.4)
        else:
            break
    return False


def click_calendar_date(page, target_date_str):
    """Click a specific date in the calendar by its aria-label."""
    dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    # Format: "Wednesday, April 23, 2026"
    day_name = dt.strftime("%A")
    month_name = dt.strftime("%B")
    label_text = f"{day_name}, {month_name} {dt.day}, {dt.year}"

    el = page.locator(f'[aria-label="{label_text}"]')
    if el.count() > 0:
        click_el(page, el)
        return True

    # Fallback: partial match
    el = page.locator(f'[aria-label*="{month_name} {dt.day}, {dt.year}"]')
    if el.count() > 0:
        click_el(page, el)
        return True

    return False


def extract_flight_results(page):
    """Extract flights from the results page after searching."""
    results = []
    items = page.locator("li").all()
    for item in items:
        text = item.inner_text().strip()
        if not re.search(r"\$[\d,]+", text):
            continue
        if len(text) < 30 or len(text) > 800:
            continue
        airlines = AIRLINE_PATTERN.findall(text)
        if not airlines:
            continue

        price_m = re.search(r"\$([\d,]+)", text)
        price = int(price_m.group(1).replace(",", "")) if price_m else 0
        if price < 100 or price > 50000:
            continue

        times = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)", text)
        durations = re.findall(r"\d+\s*hr\s*(?:\d+\s*min)?", text)
        stop_texts = re.findall(r"Nonstop|\d+\s*stop", text, re.I)

        airline_str = ", ".join(dict.fromkeys(airlines))
        if "UnitedLufthansa" in text:
            airline_str = "United, Lufthansa"
        elif "Tap Air Portugal" in text:
            airline_str = "TAP Portugal"

        results.append({
            "airline": airline_str,
            "total_price": price,
            "out_departure": times[0] if len(times) >= 1 else "",
            "out_arrival": times[1] if len(times) >= 2 else "",
            "ret_departure": times[2] if len(times) >= 3 else "",
            "ret_arrival": times[3] if len(times) >= 4 else "",
            "out_duration": durations[0] if len(durations) >= 1 else "",
            "ret_duration": durations[1] if len(durations) >= 2 else "",
            "out_stops": stop_texts[0] if len(stop_texts) >= 1 else "",
            "ret_stops": stop_texts[1] if len(stop_texts) >= 2 else "",
        })

    # Deduplicate
    seen = set()
    unique = []
    for r in results:
        key = (r["airline"], r["total_price"], r["out_departure"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def main():
    args = parse_args()
    DATA_DIR.mkdir(exist_ok=True)

    airlines_filter = set(a.strip() for a in args.airlines.split(","))
    all_records = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.headed,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US", timezone_id="America/Los_Angeles",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        ctx.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
        page = ctx.new_page()

        # ===== STEP 1: Load Google Flights in round-trip mode =====
        q = f"Flights from SFO to BCN {args.cabin} class"
        url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}"
        print(f"Loading: {url}")
        page.goto(url, timeout=30000)
        human_delay(4, 6)

        # ===== STEP 2: Open departure date picker, scan prices =====
        print("\n--- STEP 1: Scanning outbound calendar prices ---")
        dep = page.locator('input[placeholder="Departure"]').first
        click_el(page, dep)
        human_delay(2, 3)

        # Navigate to April 2026
        navigate_calendar_to(page, 2026, 4)
        human_delay(4, 6)  # Wait for prices

        # Extract April prices
        outbound_months = {(2026, 4), (2026, 5)}
        out_prices = extract_calendar_prices(page, outbound_months)

        # Also get May by navigating forward
        navigate_calendar_to(page, 2026, 5)
        human_delay(3, 5)
        out_prices.update(extract_calendar_prices(page, outbound_months))

        print(f"  Outbound calendar: {len(out_prices)} dates with prices")
        if out_prices:
            print("  Top 15 cheapest outbound dates:")
            for d, pr in sorted(out_prices.items(), key=lambda x: x[1])[:15]:
                print(f"    {d}: ${pr:,}")

        if not out_prices:
            print("  ERROR: No outbound prices found in calendar!")
            print("  Falling back to direct URL search for key dates...")
            # Fallback: we'll search specific dates directly
            browser.close()
            return

        # ===== STEP 3: For each top outbound date, explore return calendar =====
        top_out_dates = sorted(out_prices.items(), key=lambda x: x[1])[:args.top_outbound]

        print(f"\n--- STEP 2: Exploring {len(top_out_dates)} cheapest outbound dates ---")

        for rank, (out_date, out_cal_price) in enumerate(top_out_dates, 1):
            out_dt = datetime.strptime(out_date, "%Y-%m-%d")
            print(f"\n  === [{rank}/{len(top_out_dates)}] Outbound: {out_date} (calendar: ${out_cal_price:,}) ===")

            # Click the outbound date in the calendar
            # First, make sure we're on the right month
            navigate_calendar_to(page, out_dt.year, out_dt.month)
            human_delay(1, 2)

            if not click_calendar_date(page, out_date):
                print(f"    Could not click {out_date}, skipping")
                continue
            human_delay(2, 4)

            # Now the return calendar should be showing
            # Navigate to July for return dates
            navigate_calendar_to(page, 2026, 7)
            human_delay(4, 6)  # Wait for return prices to load

            # Extract return calendar prices
            ret_months = {(2026, 6), (2026, 7)}
            ret_prices = extract_calendar_prices(page, ret_months)

            # Also check June
            navigate_calendar_to(page, 2026, 6)
            human_delay(3, 4)
            ret_prices.update(extract_calendar_prices(page, ret_months))

            # Back to July
            navigate_calendar_to(page, 2026, 7)
            human_delay(2, 3)
            ret_prices.update(extract_calendar_prices(page, ret_months))

            if ret_prices:
                print(f"    Return calendar: {len(ret_prices)} dates with prices")
                # Filter to valid stay lengths
                valid_returns = {}
                for rd, rp in ret_prices.items():
                    rdt = datetime.strptime(rd, "%Y-%m-%d")
                    stay = (rdt - out_dt).days
                    if 55 <= stay <= 80:
                        valid_returns[rd] = rp

                print(f"    Valid returns (55-80d stay): {len(valid_returns)}")
                top_rets = sorted(valid_returns.items(), key=lambda x: x[1])[:args.top_return]
                for rd, rp in top_rets:
                    stay = (datetime.strptime(rd, "%Y-%m-%d") - out_dt).days
                    print(f"      {rd} ({stay}d): ${rp:,}")
            else:
                print("    No return prices found in calendar")
                valid_returns = {}
                top_rets = []

            # ===== STEP 4: Click best return date and get actual flight results =====
            if top_rets:
                best_ret_date = top_rets[0][0]
                best_ret_price = top_rets[0][1]
                best_ret_dt = datetime.strptime(best_ret_date, "%Y-%m-%d")
                stay = (best_ret_dt - out_dt).days

                print(f"\n    Selecting return: {best_ret_date} (${best_ret_price:,}, {stay}d stay)")
                navigate_calendar_to(page, best_ret_dt.year, best_ret_dt.month)
                human_delay(1, 2)

                if click_calendar_date(page, best_ret_date):
                    human_delay(1, 2)

                    # Click Done
                    done = page.locator('button:has-text("Done")')
                    if done.count() > 0:
                        click_el(page, done)
                        human_delay(1, 2)

                    # Click Search
                    search = page.locator('button:has-text("Search")')
                    if search.count() > 0:
                        click_el(page, search)
                        human_delay(6, 10)

                    # Extract results
                    flights = extract_flight_results(page)
                    interesting = [f for f in flights
                                   if any(a.lower() in f["airline"].lower() for a in airlines_filter)]

                    print(f"    Results: {len(flights)} total, {len(interesting)} matching airlines")
                    for f in interesting[:5]:
                        print(f"      {f['airline']}: ${f['total_price']:,} "
                              f"({f['out_duration']} {f['out_stops']} / {f['ret_duration']} {f['ret_stops']})")

                    # Record all matching results
                    for f in interesting:
                        all_records.append({
                            "airline": f["airline"],
                            "class": args.cabin,
                            "outbound_date": out_date,
                            "return_date": best_ret_date,
                            "stay_days": stay,
                            "out_flight": f["airline"],
                            "out_departure": f["out_departure"],
                            "out_arrival": f["out_arrival"],
                            "out_duration": f["out_duration"],
                            "out_stops": f["out_stops"],
                            "out_price": "RT",
                            "out_price_num": f["total_price"] / 2,
                            "ret_flight": f["airline"],
                            "ret_departure": f["ret_departure"],
                            "ret_arrival": f["ret_arrival"],
                            "ret_duration": f["ret_duration"],
                            "ret_stops": f["ret_stops"],
                            "ret_price": "RT",
                            "ret_price_num": f["total_price"] / 2,
                            "total_price": f"${f['total_price']:,}",
                            "total_price_num": f["total_price"],
                            "search_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "out_cal_price": out_cal_price,
                            "ret_cal_price": best_ret_price,
                        })

                    # Also search 2nd and 3rd best return dates via direct URL
                    for alt_ret_date, alt_ret_price in top_rets[1:3]:
                        alt_stay = (datetime.strptime(alt_ret_date, "%Y-%m-%d") - out_dt).days
                        print(f"\n    Alt return: {alt_ret_date} (${alt_ret_price:,}, {alt_stay}d)")

                        # Use direct URL for speed
                        q2 = f"Flights from SFO to BCN on {out_date} returning {alt_ret_date} {args.cabin} class"
                        page.goto(f"https://www.google.com/travel/flights?q={q2.replace(' ', '+')}", timeout=30000)
                        human_delay(5, 8)

                        flights2 = extract_flight_results(page)
                        interesting2 = [f for f in flights2
                                        if any(a.lower() in f["airline"].lower() for a in airlines_filter)]

                        print(f"      {len(interesting2)} matching flights")
                        for f in interesting2[:3]:
                            print(f"        {f['airline']}: ${f['total_price']:,}")

                        for f in interesting2:
                            all_records.append({
                                "airline": f["airline"],
                                "class": args.cabin,
                                "outbound_date": out_date,
                                "return_date": alt_ret_date,
                                "stay_days": alt_stay,
                                "out_flight": f["airline"],
                                "out_departure": f["out_departure"],
                                "out_arrival": f["out_arrival"],
                                "out_duration": f["out_duration"],
                                "out_stops": f["out_stops"],
                                "out_price": "RT",
                                "out_price_num": f["total_price"] / 2,
                                "ret_flight": f["airline"],
                                "ret_departure": f["ret_departure"],
                                "ret_arrival": f["ret_arrival"],
                                "ret_duration": f["ret_duration"],
                                "ret_stops": f["ret_stops"],
                                "ret_price": "RT",
                                "ret_price_num": f["total_price"] / 2,
                                "total_price": f"${f['total_price']:,}",
                                "total_price_num": f["total_price"],
                                "search_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "out_cal_price": out_cal_price,
                                "ret_cal_price": alt_ret_price,
                            })

                        human_delay(3, 6)

            # Go back to search page for next outbound date
            page.goto(url, timeout=30000)
            human_delay(3, 5)

            # Re-open date picker
            dep = page.locator('input[placeholder="Departure"]').first
            click_el(page, dep)
            human_delay(2, 3)

            human_delay(3, 6)

        browser.close()

    # ===== Output =====
    all_records.sort(key=lambda x: x["total_price_num"])

    # Save JSON
    json_path = DATA_DIR / "gf_smart_results.json"
    json_path.write_text(json.dumps(all_records, indent=2, default=str))
    print(f"\nRaw data: {json_path}")

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
        writer.writerows(all_records)
    print(f"CSV: {csv_path} ({len(all_records)} rows)")

    # HTML report
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from generate_report import generate_report
        generate_report(csv_path, args.html)
    except Exception as e:
        print(f"Report: {e}")

    # Summary
    print(f"\n{'='*70}")
    print(f"TOP 20 CHEAPEST ROUND-TRIP FARES ({args.cabin})")
    print(f"{'='*70}")
    seen = set()
    rank = 0
    for r in all_records:
        key = (r["airline"], r["total_price_num"], r["outbound_date"], r["return_date"])
        if key in seen:
            continue
        seen.add(key)
        rank += 1
        if rank > 20:
            break
        flag = "" if 60 <= r["stay_days"] <= 75 else " *REF*"
        print(f"  {rank:2d}. {r['airline']:<25s} {r['total_price']:>8s}  "
              f"{r['outbound_date']}→{r['return_date']} ({r['stay_days']}d) "
              f"{r.get('out_stops','')} / {r.get('ret_stops','')}{flag}")


if __name__ == "__main__":
    main()
