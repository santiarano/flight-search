#!/usr/bin/env python3
"""Google Flights scraper using direct URL + Playwright for interaction."""
import sys, os, time, re, json
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

SHOTS = os.path.expanduser("~/clawd/obsidian-vault/flights")

def click_el(page, locator):
    el = locator.first
    box = el.bounding_box()
    if box:
        page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
        return True
    return False

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(viewport={"width":1920,"height":1080}, locale="en-US", timezone_id="America/Los_Angeles")
    ctx.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
    page = ctx.new_page()

    # Use a direct Google Flights search URL
    # This bypasses the homepage form and goes straight to search results
    # Format: /travel/flights/search?tfs=...  or use the readable format
    # Simplest: use the explore URL that loads with params

    # Actually, the most reliable way is to use the search URL with query params
    # Google Flights URL: /travel/flights?q=...
    # Or even better, use the "search" endpoint with structured params

    # Let's try the natural language URL format first
    url = "https://www.google.com/travel/flights?q=Flights%20from%20SFO%20to%20BCN%20on%202026-04-23%20one%20way%20business%20class"
    print(f"Loading: {url}")
    page.goto(url, timeout=30000)
    time.sleep(8)

    page.screenshot(path=f"{SHOTS}/gf-direct-url.png")
    print(f"Current URL: {page.url}")

    # Check if we got results
    body = page.inner_text("body")

    # Find price matches
    prices = re.findall(r"\$([\d,]+)", body)
    print(f"\nAll prices found: {len(prices)}")

    # Look for flight-specific results
    airlines_pattern = r"(United|TAP|Tap Air Portugal|LEVEL|Iberia|American|Delta|SWISS|British Airways|Air France|KLM|Lufthansa)"
    airline_mentions = re.findall(airlines_pattern, body)
    print(f"Airlines mentioned: {set(airline_mentions)}")

    # Extract structured results
    print("\n=== Flight results ===")
    items = page.locator("li").all()
    flight_count = 0
    for item in items:
        text = item.inner_text().strip()
        if not re.search(r"\$[\d,]+", text):
            continue
        if len(text) < 30 or len(text) > 600:
            continue
        airlines = re.findall(airlines_pattern, text)
        if not airlines:
            continue

        price_m = re.search(r"\$([\d,]+)", text)
        price = f"${price_m.group(1)}" if price_m else ""
        times = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)", text)
        dur = re.search(r"(\d+)\s*hr\s*(?:(\d+)\s*min)?", text)
        dur_str = dur.group() if dur else "?"

        if "Nonstop" in text:
            stops = "nonstop"
        else:
            sm = re.search(r"(\d+)\s*stop", text)
            stops = sm.group() if sm else "?"

        print(f"  {airlines[0]}: {price} | {' -> '.join(times[:2])} | {dur_str} | {stops}")
        flight_count += 1

    print(f"\nTotal flights extracted: {flight_count}")

    if flight_count == 0:
        # Debug: print some body text
        print("\n=== Page text (first 2000) ===")
        for line in body.split("\n"):
            line = line.strip()
            if line and len(line) > 5 and len(line) < 200:
                if any(kw in line.lower() for kw in ["flight", "price", "business", "sfo", "bcn", "barcelona", "san francisco", "$"]):
                    print(f"  {line}")

    # ===== Now test the date picker approach =====
    print("\n\n=== Testing date picker with calendar prices ===")

    # Go to GF with route pre-set but no date - this should show the form
    # with calendar prices when we click departure
    url2 = "https://www.google.com/travel/flights?q=Flights+from+SFO+to+BCN+one+way+business+class"
    print(f"Loading: {url2}")
    page.goto(url2, timeout=30000)
    time.sleep(5)

    page.screenshot(path=f"{SHOTS}/gf-nodate.png")

    # Find and click on the departure date field
    print("Looking for departure date input...")
    dep_inputs = page.locator('input[placeholder="Departure"], input[aria-label="Departure"]').all()
    print(f"  Found {len(dep_inputs)} departure inputs")

    for i, dep in enumerate(dep_inputs):
        box = dep.bounding_box()
        vis = box is not None and box["width"] > 0
        print(f"  Input {i}: visible={vis}, box={box}")

    if dep_inputs:
        # Click the first visible one
        for dep in dep_inputs:
            box = dep.bounding_box()
            if box and box["width"] > 50:
                page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                print("  Clicked departure input")
                break

        time.sleep(3)
        page.screenshot(path=f"{SHOTS}/gf-datepicker-open.png")

        # Check if calendar opened
        body2 = page.inner_text("body")
        if "April" in body2 or "May" in body2 or "2026" in body2:
            print("  Calendar is open!")

            # Check for prices in calendar
            cal_prices = re.findall(r"\$[\d,]+", body2)
            print(f"  Prices in calendar area: {len(cal_prices)}")
            for cp in cal_prices[:20]:
                print(f"    {cp}")

    browser.close()
    print("\nDone!")
