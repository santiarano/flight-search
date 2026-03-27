#!/usr/bin/env python3
"""
Google Flights scraper — THE CORRECT PROCESS (CLAUDE.md steps 1-27).

1-4: Load route + cabin
5-9: Departure calendar → find cheapest outbound → click it
10-16: Return calendar → find cheapest return in stay range → click it
17: Search
18-22: Airline filter (deselect all, select targets) + stops filter + extract
23-24: Date arrow shifts for more combinations
25-27: CSV + HTML report

Usage:
    python gf_roundtrip.py --origin SFO --dest BCN --cabin business \\
      --airlines "United,Tap Air Portugal,LEVEL" \\
      --out-target 2026-05-01 --ret-target 2026-07-08 \\
      --min-stay 60 --max-stay 80 --headed
"""
import sys, os, time, re, json, csv, argparse, shutil
from datetime import datetime, timedelta
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

SCRIPTS_DIR = Path(__file__).parent
DATA_DIR = SCRIPTS_DIR / "gf_data"
VAULT_FLIGHTS = Path(os.path.expanduser("~/clawd/obsidian-vault/flights"))

MONTH_MAP = {"January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
             "July":7,"August":8,"September":9,"October":10,"November":11,"December":12}
MONTH_NAMES = {v: k for k, v in MONTH_MAP.items()}


def parse_args():
    p = argparse.ArgumentParser(description="Google Flights scraper — correct process")
    p.add_argument("--origin", required=True)
    p.add_argument("--dest", required=True)
    p.add_argument("--cabin", default="business", choices=["economy","premium economy","business","first"])
    p.add_argument("--airlines", required=True, help="Comma-separated: United,Tap Air Portugal,LEVEL")
    p.add_argument("--out-target", required=True, help="Ideal outbound date YYYY-MM-DD")
    p.add_argument("--ret-target", required=True, help="Ideal return date YYYY-MM-DD")
    p.add_argument("--min-stay", type=int, default=60)
    p.add_argument("--max-stay", type=int, default=80)
    p.add_argument("--max-stops", default="1 stop or fewer")
    p.add_argument("--top-outbound", type=int, default=3, help="Top N outbound dates to explore")
    p.add_argument("--date-shifts", type=int, default=4, help="Date arrow shifts per combo")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--csv", default=None)
    p.add_argument("--html", default=None)
    return p.parse_args()


def click_el(page, locator):
    el = locator.first
    box = el.bounding_box()
    if box and box["width"] > 0:
        page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
        return True
    return False


def extract_calendar_prices(page, target_months=None):
    prices = {}
    try:
        labeled = page.locator('[role="gridcell"] [aria-label]').all()
        for el in labeled:
            try:
                label = el.get_attribute("aria-label") or ""
                dm = re.search(r"(\w+)\s+(\d{1,2}),\s+(\d{4})", label)
                if not dm:
                    continue
                month_name, day, year = dm.group(1), int(dm.group(2)), int(dm.group(3))
                month_num = MONTH_MAP.get(month_name)
                if not month_num:
                    continue
                if target_months and month_num not in target_months:
                    continue
                date_str = f"{year}-{month_num:02d}-{day:02d}"
                parent = el.locator("..").first
                text = parent.inner_text(timeout=1000).strip()
                pm = re.search(r"\$([\d,]+)", text)
                if pm:
                    prices[date_str] = int(pm.group(1).replace(",", ""))
            except:
                continue
    except:
        pass
    return prices


def navigate_back(page, target_months):
    """Click LEFT arrow until target months have prices."""
    for _ in range(20):
        prices = extract_calendar_prices(page, target_months)
        if prices:
            return prices
        prev = page.locator('button[aria-label="Previous"]')
        if prev.count() > 0:
            click_el(page, prev)
            time.sleep(1.5)
    return {}


def navigate_forward(page, target_months):
    """Click RIGHT arrow until target months have prices."""
    for _ in range(15):
        prices = extract_calendar_prices(page, target_months)
        if prices:
            return prices
        nxt = page.locator('button[aria-label="Next"]')
        if nxt.count() > 0:
            click_el(page, nxt)
            time.sleep(1.5)
    return {}


def click_date(page, date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    label = f"{dt.strftime('%A')}, {dt.strftime('%B')} {dt.day}, {dt.year}"
    el = page.locator(f'[aria-label="{label}"]')
    if el.count() > 0:
        click_el(page, el)
        return True
    el = page.locator(f'[aria-label*="{dt.strftime("%B")} {dt.day}, {dt.year}"]')
    if el.count() > 0:
        click_el(page, el)
        return True
    return False


def extract_results(page):
    flights = []
    try:
        items = page.locator("li").all()
        for item in items:
            try:
                text = item.inner_text(timeout=2000).strip()
            except:
                continue
            if len(text) < 30 or len(text) > 800:
                continue
            price_m = re.search(r"\$([\d,]+)", text)
            if not price_m:
                continue
            price = int(price_m.group(1).replace(",", ""))
            if price < 500 or price > 50000:
                continue
            airlines = re.findall(
                r"(United|Tap Air Portugal|LEVEL|Iberia|Lufthansa|SWISS|American|Delta|"
                r"Alaska|Condor|KLM|Air France|British Airways)", text)[:2]
            if not airlines:
                continue
            stops = re.findall(r"Nonstop|\d+\s*stop", text, re.I)
            durs = re.findall(r"\d+\s*hr\s*(?:\d+\s*min)?", text)
            times_found = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)", text)
            flights.append({
                "airline": ", ".join(dict.fromkeys(airlines)),
                "price": price,
                "stops": stops[0] if stops else "?",
                "duration": durs[0] if durs else "?",
                "dep": times_found[0] if times_found else "",
                "arr": times_found[1] if len(times_found) > 1 else "",
            })
    except:
        pass
    seen = set()
    unique = []
    for f in flights:
        key = (f["airline"][:20], f["price"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return sorted(unique, key=lambda x: x["price"])


def make_result_row(f, cabin, out_date, ret_date, stay):
    return {
        "airline": f["airline"], "class": cabin,
        "outbound_date": out_date, "return_date": ret_date, "stay_days": stay,
        "out_flight": f["airline"], "out_departure": f.get("dep",""),
        "out_arrival": f.get("arr",""), "out_duration": f["duration"],
        "out_stops": f["stops"], "out_price": "RT",
        "ret_flight": f["airline"], "ret_departure": "", "ret_arrival": "",
        "ret_duration": "", "ret_stops": "", "ret_price": "RT",
        "total_price": f"${f['price']:,}", "total_price_num": f["price"],
        "search_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def main():
    args = parse_args()
    DATA_DIR.mkdir(exist_ok=True)
    VAULT_FLIGHTS.mkdir(parents=True, exist_ok=True)

    slug = f"{args.origin.lower()}-{args.dest.lower()}"
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    history_dir = VAULT_FLIGHTS / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.csv or str(VAULT_FLIGHTS / f"{slug}-roundtrip.csv")
    html_path = args.html or str(VAULT_FLIGHTS / f"{slug}-report.html")

    out_target_dt = datetime.strptime(args.out_target, "%Y-%m-%d")
    out_months = {out_target_dt.month}
    # Include adjacent month
    if out_target_dt.month < 12:
        out_months.add(out_target_dt.month + 1)
    airline_names = [a.strip() for a in args.airlines.split(",")]

    all_results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.headed,
            args=["--disable-blink-features=AutomationControlled","--no-sandbox"])
        ctx = browser.new_context(
            viewport={"width":1920,"height":1080},
            locale="en-US", timezone_id="America/Los_Angeles")
        ctx.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
        page = ctx.new_page()

        # STEPS 1-4
        print(f"STEPS 1-4: {args.origin}->{args.dest}, {args.cabin}, round-trip")
        url = f"https://www.google.com/travel/flights?q=Flights+from+{args.origin}+to+{args.dest}+{args.cabin}+class"
        page.goto(url, timeout=30000)
        time.sleep(8)

        # STEP 5
        print("STEP 5: Opening departure calendar")
        click_el(page, page.locator('input[placeholder="Departure"]').first)
        time.sleep(3)

        # STEPS 6-7: Navigate LEFT to outbound month
        print(f"STEPS 6-7: Navigating to {MONTH_NAMES.get(out_target_dt.month)}")
        time.sleep(3)
        out_prices = navigate_back(page, out_months)
        time.sleep(4)
        out_prices.update(extract_calendar_prices(page, out_months))
        print(f"  {len(out_prices)} outbound prices found")

        if not out_prices:
            print("ERROR: No outbound prices!")
            browser.close()
            return

        # STEP 8
        top_out = sorted(out_prices.items(), key=lambda x: x[1])[:args.top_outbound]
        print(f"STEP 8: Top {len(top_out)} cheapest:")
        for d, pr in top_out:
            print(f"  {d}: ${pr:,}")

        # ITERATE outbound dates
        for out_rank, (out_date, out_cal) in enumerate(top_out, 1):
            out_dt = datetime.strptime(out_date, "%Y-%m-%d")
            earliest_ret = out_dt + timedelta(days=args.min_stay)
            latest_ret = out_dt + timedelta(days=args.max_stay)
            ret_months = set()
            d = earliest_ret
            while d <= latest_ret:
                ret_months.add(d.month)
                d += timedelta(days=28)

            print(f"\n{'='*50}")
            print(f"  #{out_rank}: {out_date} (${out_cal:,})")
            print(f"{'='*50}")

            # STEP 9: Click outbound
            if not click_date(page, out_date):
                print("  Could not click outbound, skipping")
                click_el(page, page.locator('input[placeholder="Departure"]').first)
                time.sleep(2)
                navigate_back(page, out_months)
                continue
            time.sleep(3)

            # STEPS 10-14: Return calendar
            print(f"  Return: navigating to {[MONTH_NAMES.get(m) for m in sorted(ret_months)]}")
            ret_prices = navigate_forward(page, ret_months)
            time.sleep(4)
            ret_prices.update(extract_calendar_prices(page, ret_months))

            valid = {d_s: pr for d_s, pr in ret_prices.items()
                     if args.min_stay <= (datetime.strptime(d_s, "%Y-%m-%d") - out_dt).days <= args.max_stay}

            if not valid:
                print(f"  No valid returns ({args.min_stay}-{args.max_stay}d)")
                page.keyboard.press("Escape")
                time.sleep(1)
                click_el(page, page.locator('input[placeholder="Departure"]').first)
                time.sleep(2)
                navigate_back(page, out_months)
                continue

            top_rets = sorted(valid.items(), key=lambda x: x[1])[:3]
            for d_s, pr in top_rets:
                stay = (datetime.strptime(d_s, "%Y-%m-%d") - out_dt).days
                print(f"  Return: {d_s} ({stay}d) ${pr:,}")

            # STEPS 15-16: Click return + Done
            ret_date = top_rets[0][0]
            ret_stay = (datetime.strptime(ret_date, "%Y-%m-%d") - out_dt).days
            click_date(page, ret_date)
            time.sleep(2)
            done = page.locator('button:has-text("Done")')
            if done.count() > 0:
                click_el(page, done)
                time.sleep(2)
            page.keyboard.press("Escape")
            time.sleep(1)

            # STEP 17: Search
            search_btn = page.locator('button:has-text("Search")')
            if search_btn.count() > 0:
                click_el(page, search_btn)
            time.sleep(10)

            # STEPS 18-20: Airline filter
            try:
                btn = page.locator('button:has-text("Airlines"), button:has-text("All airlines")')
                if btn.count() > 0:
                    click_el(page, btn)
                    time.sleep(2)
                    toggle = page.locator('button[role="switch"][aria-label="Select all airlines"]')
                    if toggle.count() > 0 and toggle.get_attribute("aria-checked") == "true":
                        toggle.first.click(force=True)
                        time.sleep(2)
                    for name in airline_names:
                        li = page.locator(f'li[ssk*="{name}"]')
                        if li.count() > 0:
                            li.first.click(force=True)
                            time.sleep(0.5)
                    page.keyboard.press("Escape")
                    time.sleep(3)
            except:
                page.keyboard.press("Escape")

            # STEP 21: Stops
            try:
                btn = page.locator('button:has-text("Stops")')
                if btn.count() > 0:
                    click_el(page, btn)
                    time.sleep(1)
                    el = page.locator(f'label:has-text("{args.max_stops}")')
                    if el.count() > 0:
                        click_el(page, el)
                    page.keyboard.press("Escape")
                    time.sleep(2)
            except:
                pass

            # STEP 22: Extract
            page.mouse.wheel(0, 500)
            time.sleep(2)
            try:
                for txt in ["more flights", "View more", "Other flights"]:
                    more = page.locator(f'button:has-text("{txt}")')
                    if more.count() > 0:
                        click_el(page, more)
                        time.sleep(3)
                        break
            except:
                pass

            results = extract_results(page)
            print(f"  {len(results)} flights")
            for f in results[:5]:
                print(f"    {f['airline']:<25s} ${f['price']:>7,}  {f['stops']}")
                all_results.append(make_result_row(f, args.cabin, out_date, ret_date, ret_stay))

            # STEPS 23-24: Date shifts
            for shift in range(args.date_shifts):
                try:
                    arrows = page.locator('button[aria-label*="Later"], button[aria-label*="later"]')
                    if arrows.count() > 0:
                        click_el(page, arrows)
                        time.sleep(6)
                        shifted = extract_results(page)
                        for f in shifted[:2]:
                            all_results.append(make_result_row(f, args.cabin, f"shift+{shift+1}", ret_date, ret_stay))
                    else:
                        break
                except:
                    break

            # Alt returns via direct URL
            for alt_ret, _ in top_rets[1:]:
                alt_stay = (datetime.strptime(alt_ret, "%Y-%m-%d") - out_dt).days
                try:
                    q = f"Flights from {args.origin} to {args.dest} on {out_date} returning {alt_ret} {args.cabin} class"
                    page.goto(f"https://www.google.com/travel/flights?q={q.replace(' ','+')}", timeout=30000)
                    time.sleep(8)
                    for f in extract_results(page)[:3]:
                        all_results.append(make_result_row(f, args.cabin, out_date, alt_ret, alt_stay))
                except:
                    pass

            # Reset for next outbound
            page.goto(url, timeout=30000)
            time.sleep(8)
            click_el(page, page.locator('input[placeholder="Departure"]').first)
            time.sleep(3)
            navigate_back(page, out_months)
            time.sleep(3)

        browser.close()

    # STEPS 25-27
    all_results.sort(key=lambda x: x.get("total_price_num", 99999))

    Path(str(DATA_DIR / f"{slug}_results.json")).write_text(json.dumps(all_results, indent=2, default=str))

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    fields = ["airline","class","outbound_date","return_date","stay_days",
              "out_flight","out_departure","out_arrival","out_duration","out_stops","out_price",
              "ret_flight","ret_departure","ret_arrival","ret_duration","ret_stops","ret_price",
              "total_price","search_date"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_results)
    print(f"\nCSV: {csv_path} ({len(all_results)} rows)")

    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from generate_report import generate_report
        generate_report(csv_path, html_path)
    except Exception as e:
        print(f"Report: {e}")

    shutil.copy2(csv_path, str(history_dir / f"{slug}-{ts}.csv"))
    if os.path.exists(html_path):
        shutil.copy2(html_path, str(history_dir / f"{slug}-{ts}.html"))

    print(f"\n{'='*60}")
    print(f"TOP 20")
    print(f"{'='*60}")
    seen = set()
    rank = 0
    for r in all_results:
        key = (r["airline"][:20], r.get("total_price_num",0), r["outbound_date"], r["return_date"])
        if key in seen:
            continue
        seen.add(key)
        rank += 1
        if rank > 20:
            break
        print(f"  {rank:2d}. {r['airline']:<25s} {r['total_price']:>8s}  {r['outbound_date']} -> {r['return_date']} ({r['stay_days']}d)")


if __name__ == "__main__":
    main()
