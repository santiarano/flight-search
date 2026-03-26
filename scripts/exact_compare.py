#!/usr/bin/env python3
"""
Find the EXACT same flights from US that Spain found cheapest,
and compare the prices side by side.
"""
import sys, os, time, re, json
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright
import urllib.request
from pathlib import Path

SHOTS = Path(os.path.expanduser("~/clawd/obsidian-vault/flights/screenshots"))
SHOTS.mkdir(parents=True, exist_ok=True)

# Bright Data Web Unlocker for Spain searches
BD_KEY = json.loads(Path(__file__).parent.joinpath("gf_data/brightdata_creds.json").read_text())["api_key"]

AIRLINE_RE = re.compile(
    r"(United|Tap Air Portugal|LEVEL|Iberia|Lufthansa|SWISS|American|Delta|"
    r"Alaska|Condor|KLM|Air France|British Airways|LOT|Aer Lingus|Turkish|Norse)"
)


def click_el(page, locator):
    el = locator.first
    box = el.bounding_box()
    if box and box["width"] > 0:
        page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
        return True
    return False


def extract_flights_from_page(page):
    """Extract all flights from a Playwright Google Flights page."""
    flights = []
    items = page.locator("li").all()
    for item in items:
        text = item.inner_text().strip()
        if len(text) < 30 or len(text) > 800:
            continue
        price_m = re.search(r"\$([\d,]+)", text)
        if not price_m:
            continue
        price = int(price_m.group(1).replace(",", ""))
        if price < 500 or price > 50000:
            continue
        airlines = AIRLINE_RE.findall(text)
        if not airlines:
            continue
        stops = re.findall(r"Nonstop|\d+\s*stop", text, re.I)
        durs = re.findall(r"\d+\s*hr\s*(?:\d+\s*min)?", text)
        times_found = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)", text)
        airline = ", ".join(dict.fromkeys(airlines))
        flights.append({
            "airline": airline, "price": price,
            "stops": stops[0] if stops else "?",
            "duration": durs[0] if durs else "?",
            "dep": times_found[0] if times_found else "",
        })
    # Dedupe
    seen = set()
    unique = []
    for f in flights:
        key = (f["airline"][:25], f["price"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return sorted(unique, key=lambda x: x["price"])


def extract_flights_from_html(html):
    """Extract flights from raw HTML (Bright Data response)."""
    text = re.sub(r"<[^>]+>", "|", html)
    flights = []
    segments = text.split("round trip")
    for seg in segments:
        pm = re.search(r"\u20ac\s*([\d,.]+)", seg)
        if not pm:
            continue
        ps = pm.group(1).replace(",", "")
        if "." in ps and len(ps.split(".")[-1]) == 3:
            ps = ps.replace(".", "")
        try:
            price = int(float(ps))
        except:
            continue
        if price < 500 or price > 50000:
            continue
        airlines = AIRLINE_RE.findall(seg)
        if not airlines:
            continue
        stops = re.findall(r"Nonstop|\d+\s*stop", seg, re.I)
        durs = re.findall(r"\d+\s*hr\s*(?:\d+\s*min)?", seg)
        airline = ", ".join(dict.fromkeys(airlines))
        flights.append({
            "airline": airline, "price_eur": price,
            "stops": stops[0] if stops else "?",
            "duration": durs[0] if durs else "?",
        })
    seen = set()
    unique = []
    for f in flights:
        key = (f["airline"][:25], f["price_eur"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return sorted(unique, key=lambda x: x["price_eur"])


def fetch_spain_html(out_date, ret_date):
    """Fetch Google Flights from Spain via Bright Data Web Unlocker."""
    q = f"Flights from SFO to BCN on {out_date} returning {ret_date} business class"
    url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}&curr=EUR&hl=en"
    payload = json.dumps({
        "zone": "web_unlocker1", "url": url, "country": "es", "format": "raw",
    }).encode()
    req = urllib.request.Request("https://api.brightdata.com/request",
        data=payload,
        headers={"Authorization": f"Bearer {BD_KEY}", "Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=60)
    return resp.read().decode("utf-8", errors="replace")


def main():
    dates = [
        ("2026-04-30", "2026-07-08"),
        ("2026-04-26", "2026-07-08"),
        ("2026-05-04", "2026-07-08"),
    ]

    all_comparisons = []

    # === STEP 1: Get Spain prices via Bright Data ===
    print(f"{'#'*70}")
    print(f"  STEP 1: Fetching prices from SPAIN (Bright Data Web Unlocker)")
    print(f"{'#'*70}\n")

    spain_results = {}
    for out_d, ret_d in dates:
        print(f"  {out_d} -> {ret_d}...", end=" ", flush=True)
        html = fetch_spain_html(out_d, ret_d)
        # Save HTML for screenshot
        html_path = SHOTS / f"spain-html-{out_d}.html"
        html_path.write_text(html, encoding="utf-8")
        flights = extract_flights_from_html(html)
        spain_results[(out_d, ret_d)] = flights
        if flights:
            print(f"{len(flights)} flights")
            for f in flights:
                print(f"    {f['airline']:<40s} \u20ac{f['price_eur']:>7,}  {f['stops']:>10s}  {f['duration']}")
        else:
            print("0 flights")
        time.sleep(2)

    # Render Spain HTML as screenshots
    print("\n  Generating Spain screenshots...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for out_d, ret_d in dates:
            html_path = SHOTS / f"spain-html-{out_d}.html"
            if html_path.exists():
                pg = browser.new_page(viewport={"width": 1920, "height": 1080})
                pg.goto(f"file:///{str(html_path).replace(os.sep, '/')}")
                time.sleep(3)
                pg.mouse.wheel(0, 200)
                time.sleep(1)
                pg.screenshot(path=str(SHOTS / f"spain-{out_d}.png"))
                pg.close()
        browser.close()
    print("  Done")

    # === STEP 2: Get US prices via Playwright ===
    print(f"\n{'#'*70}")
    print(f"  STEP 2: Fetching prices from US (Playwright direct)")
    print(f"{'#'*70}\n")

    us_results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US", timezone_id="America/Los_Angeles",
        )
        ctx.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
        page = ctx.new_page()

        for out_d, ret_d in dates:
            print(f"  {out_d} -> {ret_d}...", end=" ", flush=True)
            q = f"Flights from SFO to BCN on {out_d} returning {ret_d} business class"
            url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}&curr=USD&hl=en"
            page.goto(url, timeout=45000)
            time.sleep(10)
            page.mouse.wheel(0, 500)
            time.sleep(2)

            # Expand
            for txt in ["more flights", "View more", "Other flights"]:
                try:
                    more = page.locator(f'button:has-text("{txt}")')
                    if more.count() > 0:
                        click_el(page, more)
                        time.sleep(5)
                        break
                except:
                    pass

            page.mouse.wheel(0, 800)
            time.sleep(2)
            page.screenshot(path=str(SHOTS / f"us-{out_d}.png"))

            flights = extract_flights_from_page(page)
            us_results[(out_d, ret_d)] = flights
            print(f"{len(flights)} flights")
            for f in flights:
                marker = " <<<" if "Alaska" in f["airline"] or "Condor" in f["airline"] else ""
                print(f"    {f['airline']:<40s} ${f['price']:>7,}  {f['stops']:>10s}  {f['duration']}{marker}")

            time.sleep(5)

        browser.close()

    # === STEP 3: Match exact flights ===
    print(f"\n{'#'*70}")
    print(f"  PRICE COMPARISON: Exact same flights, US vs Spain")
    print(f"{'#'*70}")
    print(f"\n  {'Dates':<26s} {'Airline':<35s} {'US ($)':>9s} {'ES (\u20ac)':>9s} {'ES ~$':>9s} {'Savings':>12s}")
    print(f"  {'-'*100}")

    for out_d, ret_d in dates:
        es_flights = spain_results.get((out_d, ret_d), [])
        us_flights = us_results.get((out_d, ret_d), [])

        for es_f in es_flights:
            es_airlines = set(a.lower() for a in es_f["airline"].split(", "))
            # Find matching US flight (same airline combo)
            for us_f in us_flights:
                us_airlines = set(a.lower() for a in us_f["airline"].split(", "))
                if es_airlines & us_airlines:
                    es_usd = round(es_f["price_eur"] * 1.08)
                    savings = us_f["price"] - es_usd
                    pct = (savings / us_f["price"] * 100) if us_f["price"] else 0
                    color_marker = "CHEAPER" if savings > 0 else "MORE EXPENSIVE"
                    dates_str = f"{out_d} -> {ret_d}"
                    print(f"  {dates_str:<26s} {us_f['airline']:<35s} ${us_f['price']:>7,}  \u20ac{es_f['price_eur']:>7,}  ${es_usd:>7,}  ${savings:>+7,} ({pct:+.0f}%)")

                    all_comparisons.append({
                        "dates": dates_str,
                        "airline": us_f["airline"],
                        "us_price": us_f["price"],
                        "es_price_eur": es_f["price_eur"],
                        "es_price_usd": es_usd,
                        "savings": savings,
                        "pct": round(pct, 1),
                        "us_screenshot": str(SHOTS / f"us-{out_d}.png"),
                        "es_screenshot": str(SHOTS / f"spain-{out_d}.png"),
                    })
                    break

    # Summary
    if all_comparisons:
        avg = sum(c["savings"] for c in all_comparisons) / len(all_comparisons)
        best = max(all_comparisons, key=lambda c: c["savings"])
        print(f"\n  {'='*60}")
        print(f"  Matched flights: {len(all_comparisons)}")
        print(f"  Average savings from Spain: ${avg:+,.0f}")
        print(f"  Best saving: ${best['savings']:+,} on {best['dates']} ({best['airline']})")
        print(f"  Bright Data cost: ${len(dates) * 0.003:.3f}")
        print(f"\n  Screenshots: {SHOTS}")

    # Save comparison JSON
    json_path = Path(__file__).parent / "gf_data" / "exact_comparison.json"
    json_path.write_text(json.dumps(all_comparisons, indent=2))
    print(f"  JSON: {json_path}")


if __name__ == "__main__":
    main()
