#!/usr/bin/env python3
"""
Search airline websites directly from Spain via Bright Data residential proxy.
Compares prices on united.com, flytap.com, and flylevel.com from US vs Spain IP.
"""
import sys, os, time, re, json
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from playwright.sync_api import sync_playwright

SHOTS = Path(os.path.expanduser("~/clawd/obsidian-vault/flights/screenshots"))
SHOTS.mkdir(parents=True, exist_ok=True)

# Bright Data residential proxy for Spain
BD_PROXY = {
    "server": "http://brd.superproxy.io:33335",
    "username": "brd-customer-hl_3f584c66-zone-residential_proxy1-country-es",
    "password": "fd3ze4fgm7g9",
}


def click_el(page, locator):
    el = locator.first
    box = el.bounding_box()
    if box and box["width"] > 0:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        return True
    return False


def search_google_flights(page, origin, dest, out_date, ret_date, cabin, label, screenshot_prefix):
    """Search Google Flights and extract results."""
    q = f"Flights from {origin} to {dest} on {out_date} returning {ret_date} {cabin} class"
    url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}&hl=en"

    print(f"  Loading Google Flights ({label})...")
    page.goto(url, timeout=60000)
    time.sleep(12)

    page.mouse.wheel(0, 500)
    time.sleep(2)

    # Expand more flights
    try:
        for txt in ["more flights", "View more", "Other flights"]:
            more = page.locator(f'button:has-text("{txt}")')
            if more.count() > 0:
                click_el(page, more)
                time.sleep(5)
                break
    except:
        pass

    page.mouse.wheel(0, 500)
    time.sleep(2)

    page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-top.png"))
    page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-full.png"), full_page=True)

    # Extract flights
    flights = []
    airline_re = re.compile(
        r"(United|Tap Air Portugal|LEVEL|Iberia|American|Delta|SWISS|"
        r"British Airways|Air France|KLM|Lufthansa|Alaska|Condor|LOT|Aer Lingus)"
    )

    items = page.locator("li").all()
    for item in items:
        text = item.inner_text().strip()
        if len(text) < 30 or len(text) > 800:
            continue
        price_m = re.search(r"\$([\d,]+)", text) or re.search(r"\u20ac\s*([\d,.]+)", text)
        if not price_m:
            continue
        airlines = airline_re.findall(text)
        if not airlines:
            continue
        ps = price_m.group(1).replace(",", "")
        if "." in ps and len(ps.split(".")[-1]) == 3:
            ps = ps.replace(".", "")
        try:
            price = int(float(ps))
        except:
            continue
        if price < 500 or price > 50000:
            continue
        stops = re.findall(r"Nonstop|\d+\s*stop", text, re.I)
        durs = re.findall(r"\d+\s*hr\s*(?:\d+\s*min)?", text)
        airline = ", ".join(dict.fromkeys(airlines))
        flights.append({"airline": airline, "price": price, "stops": stops[0] if stops else "?", "duration": durs[0] if durs else "?"})

    # Dedupe
    seen = set()
    unique = []
    for f in flights:
        key = (f["airline"][:25], f["price"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return sorted(unique, key=lambda x: x["price"])


def search_united(page, origin, dest, out_date, ret_date, label, screenshot_prefix):
    """Search united.com for business class prices."""
    url = (
        f"https://www.united.com/en-us/fsr/choose-flights?"
        f"f={origin}&t={dest}&d={out_date}&r={ret_date}&px=1&taxng=1&newHP=True&clm=7&st=bestmatches"
    )
    print(f"  Loading united.com ({label})...")
    try:
        page.goto(url, timeout=60000)
        time.sleep(15)
    except Exception as e:
        print(f"    Load error: {str(e)[:60]}")
        page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-error.png"))
        return []

    page.mouse.wheel(0, 300)
    time.sleep(2)
    page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-top.png"))
    page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-full.png"), full_page=True)

    # Extract prices from united.com
    body = page.inner_text("body")
    prices = []
    # United shows prices like "$5,274" or "USD 5,274" or "EUR 4,500"
    for m in re.finditer(r"\$\s*([\d,]+)|\u20ac\s*([\d,.]+)|USD\s*([\d,]+)|EUR\s*([\d,.]+)", body):
        raw = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        raw = raw.replace(",", "")
        if "." in raw and len(raw.split(".")[-1]) == 3:
            raw = raw.replace(".", "")
        try:
            p = int(float(raw))
        except:
            continue
        if 500 < p < 50000:
            prices.append(p)

    return sorted(set(prices))


def search_tap(page, origin, dest, out_date, ret_date, label, screenshot_prefix):
    """Search flytap.com for business class prices."""
    # TAP uses a different URL format
    url = (
        f"https://www.flytap.com/en-us/booking?"
        f"origin={origin}&destination={dest}&departureDate={out_date}&returnDate={ret_date}"
        f"&adults=1&children=0&infants=0&cabinClass=C"
    )
    print(f"  Loading flytap.com ({label})...")
    try:
        page.goto(url, timeout=60000)
        time.sleep(15)
    except Exception as e:
        print(f"    Load error: {str(e)[:60]}")
        page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-error.png"))
        return []

    page.mouse.wheel(0, 300)
    time.sleep(2)
    page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-top.png"))
    page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-full.png"), full_page=True)

    body = page.inner_text("body")
    prices = []
    for m in re.finditer(r"\$\s*([\d,]+)|\u20ac\s*([\d,.]+)|USD\s*([\d,]+)|EUR\s*([\d,.]+)", body):
        raw = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        raw = raw.replace(",", "")
        if "." in raw and len(raw.split(".")[-1]) == 3:
            raw = raw.replace(".", "")
        try:
            p = int(float(raw))
        except:
            continue
        if 500 < p < 50000:
            prices.append(p)

    return sorted(set(prices))


def search_level(page, origin, dest, out_date, ret_date, label, screenshot_prefix):
    """Search flylevel.com for premium economy prices."""
    url = (
        f"https://www.flylevel.com/Flight/ExternalSelect?"
        f"o1={origin}&d1={dest}&dd1={out_date}&dd2={ret_date}"
        f"&ADT=1&CHD=0&Inl=0&r=TRUE&mm=FALSE"
    )
    print(f"  Loading flylevel.com ({label})...")
    try:
        page.goto(url, timeout=60000)
        time.sleep(15)
    except Exception as e:
        print(f"    Load error: {str(e)[:60]}")
        page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-error.png"))
        return []

    page.mouse.wheel(0, 300)
    time.sleep(2)
    page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-top.png"))
    page.screenshot(path=str(SHOTS / f"{screenshot_prefix}-full.png"), full_page=True)

    body = page.inner_text("body")
    prices = []
    for m in re.finditer(r"\$\s*([\d,]+)|\u20ac\s*([\d,.]+)|USD\s*([\d,]+)|EUR\s*([\d,.]+)", body):
        raw = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        raw = raw.replace(",", "")
        if "." in raw and len(raw.split(".")[-1]) == 3:
            raw = raw.replace(".", "")
        try:
            p = int(float(raw))
        except:
            continue
        if 100 < p < 50000:
            prices.append(p)

    return sorted(set(prices))


def main():
    out_date = "2026-04-30"
    ret_date = "2026-07-08"
    origin = "SFO"
    dest = "BCN"

    all_results = {}

    with sync_playwright() as p:
        # === SPAIN SEARCH (residential proxy) ===
        print(f"\n{'#'*70}")
        print(f"  SEARCHING FROM SPAIN (Bright Data residential proxy)")
        print(f"  {origin} -> {dest} | {out_date} -> {ret_date} | Business")
        print(f"{'#'*70}\n")

        browser_es = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--ignore-certificate-errors"],
            proxy=BD_PROXY,
        )
        ctx_es = browser_es.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US", timezone_id="Europe/Madrid",
            ignore_https_errors=True,
        )
        ctx_es.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
        page_es = ctx_es.new_page()

        # Verify IP
        page_es.goto("http://httpbin.org/ip", timeout=20000)
        es_ip = page_es.inner_text("body").strip()
        print(f"  Spain IP: {es_ip}\n")

        # Search each airline from Spain
        print("--- United.com from Spain ---")
        es_united = search_united(page_es, origin, dest, out_date, ret_date, "Spain", "es-united")
        print(f"  Prices found: {es_united}\n")

        print("--- TAP (flytap.com) from Spain ---")
        es_tap = search_tap(page_es, origin, dest, out_date, ret_date, "Spain", "es-tap")
        print(f"  Prices found: {es_tap}\n")

        print("--- LEVEL (flylevel.com) from Spain ---")
        es_level = search_level(page_es, origin, dest, out_date, ret_date, "Spain", "es-level")
        print(f"  Prices found: {es_level}\n")

        # Google Flights from Spain (for reference)
        print("--- Google Flights from Spain ---")
        es_gf = search_google_flights(page_es, origin, dest, out_date, ret_date, "business", "Spain", "es-gf")
        for f in es_gf[:5]:
            print(f"  {f['airline']:<35s} \u20ac{f['price']:>7,}  {f['stops']}")

        browser_es.close()

        # === US SEARCH (no proxy) ===
        print(f"\n{'#'*70}")
        print(f"  SEARCHING FROM US (direct connection)")
        print(f"{'#'*70}\n")

        browser_us = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx_us = browser_us.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US", timezone_id="America/Los_Angeles",
        )
        ctx_us.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
        page_us = ctx_us.new_page()

        print("--- United.com from US ---")
        us_united = search_united(page_us, origin, dest, out_date, ret_date, "US", "us-united")
        print(f"  Prices found: {us_united}\n")

        print("--- TAP (flytap.com) from US ---")
        us_tap = search_tap(page_us, origin, dest, out_date, ret_date, "US", "us-tap")
        print(f"  Prices found: {us_tap}\n")

        print("--- LEVEL (flylevel.com) from US ---")
        us_level = search_level(page_us, origin, dest, out_date, ret_date, "US", "us-level")
        print(f"  Prices found: {us_level}\n")

        # Google Flights from US
        print("--- Google Flights from US ---")
        us_gf = search_google_flights(page_us, origin, dest, out_date, ret_date, "business", "US", "us-gf")
        for f in us_gf[:5]:
            print(f"  {f['airline']:<35s} ${f['price']:>7,}  {f['stops']}")

        browser_us.close()

    # === COMPARISON ===
    print(f"\n{'='*70}")
    print(f"  PRICE COMPARISON: US vs SPAIN (airline direct websites)")
    print(f"  {origin}-{dest} | {out_date} -> {ret_date} | Business class")
    print(f"{'='*70}")
    print(f"\n  {'Source':<25s} {'US Price':>12s} {'Spain Price':>12s} {'Savings':>12s}")
    print(f"  {'-'*61}")

    def compare_row(label, us_prices, es_prices, us_sym="$", es_sym="\u20ac"):
        if us_prices and es_prices:
            us_p = min(us_prices)
            es_p = min(es_prices)
            es_usd = round(es_p * 1.08) if es_sym == "\u20ac" else es_p
            diff = us_p - es_usd
            print(f"  {label:<25s} {us_sym}{us_p:>10,}  {es_sym}{es_p:>10,}  ${diff:>+10,}")
        elif us_prices:
            print(f"  {label:<25s} {us_sym}{min(us_prices):>10,}  {'N/A':>12s}  {'':>12s}")
        elif es_prices:
            print(f"  {label:<25s} {'N/A':>12s}  {es_sym}{min(es_prices):>10,}  {'':>12s}")
        else:
            print(f"  {label:<25s} {'N/A':>12s}  {'N/A':>12s}  {'':>12s}")

    compare_row("United.com", us_united, es_united)
    compare_row("flytap.com (TAP)", us_tap, es_tap)
    compare_row("flylevel.com (LEVEL)", us_level, es_level)

    if us_gf and es_gf:
        us_best = min(us_gf, key=lambda x: x["price"])
        es_best = min(es_gf, key=lambda x: x["price"])
        es_usd = round(es_best["price"] * 1.08)
        diff = us_best["price"] - es_usd
        print(f"  {'Google Flights':<25s} ${us_best['price']:>10,}  \u20ac{es_best['price']:>10,}  ${diff:>+10,}")

    print(f"\n  Screenshots saved to: {SHOTS}")
    print(f"  Bright Data cost: ~$0.012 (4 requests via residential proxy)")


if __name__ == "__main__":
    main()
