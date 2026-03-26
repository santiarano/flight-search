#!/usr/bin/env python3
"""
Google Flights scraper — general purpose, any route/dates/class/airline.
Searches actual round-trip or one-way fares via Playwright.

Usage:
    python gf_roundtrip.py --origin SFO --dest BCN --out-start 2026-04-20 --out-end 2026-05-16 \
        --ret-start 2026-06-28 --ret-end 2026-07-22 --cabin business --airlines "United,TAP"
    python gf_roundtrip.py --origin SFO --dest BCN --out-dates 2026-05-12 --ret-dates 2026-07-08
    python gf_roundtrip.py --origin SFO --dest BCN --out-dates 2026-05-12 --one-way --cabin business
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
VAULT_FLIGHTS = Path(os.path.expanduser("~/clawd/obsidian-vault/flights"))

# Country presets: locale, timezone, google domain, currency, geolocation
COUNTRY_PRESETS = {
    "US": {"locale": "en-US", "tz": "America/Los_Angeles", "domain": "google.com", "currency": "USD",
           "geo": {"latitude": 37.7749, "longitude": -122.4194}},
    "ES": {"locale": "es-ES", "tz": "Europe/Madrid", "domain": "google.es", "currency": "EUR",
           "geo": {"latitude": 40.4168, "longitude": -3.7038}},
    "UK": {"locale": "en-GB", "tz": "Europe/London", "domain": "google.co.uk", "currency": "GBP",
           "geo": {"latitude": 51.5074, "longitude": -0.1278}},
    "DE": {"locale": "de-DE", "tz": "Europe/Berlin", "domain": "google.de", "currency": "EUR",
           "geo": {"latitude": 52.5200, "longitude": 13.4050}},
    "FR": {"locale": "fr-FR", "tz": "Europe/Paris", "domain": "google.fr", "currency": "EUR",
           "geo": {"latitude": 48.8566, "longitude": 2.3522}},
    "MX": {"locale": "es-MX", "tz": "America/Mexico_City", "domain": "google.com.mx", "currency": "MXN",
           "geo": {"latitude": 19.4326, "longitude": -99.1332}},
    "BR": {"locale": "pt-BR", "tz": "America/Sao_Paulo", "domain": "google.com.br", "currency": "BRL",
           "geo": {"latitude": -23.5505, "longitude": -46.6333}},
    "JP": {"locale": "ja-JP", "tz": "Asia/Tokyo", "domain": "google.co.jp", "currency": "JPY",
           "geo": {"latitude": 35.6762, "longitude": 139.6503}},
}

AIRLINE_PATTERN = re.compile(
    r"(United(?:Lufthansa)?|United|TAP|Tap Air Portugal|LEVEL|Iberia|American|Delta|"
    r"SWISS|British Airways|Air France|KLM|Lufthansa|LOT|Aer Lingus|Finnair|Turkish|Norse|"
    r"Emirates|Qatar|Etihad|Singapore|Cathay|ANA|JAL|Korean Air|Avianca|LATAM|"
    r"Vueling|Ryanair|easyJet|Norwegian|JetBlue|Southwest|Alaska|Spirit|Frontier|"
    r"Air Canada|WestJet|Condor|Icelandair|SAS|Wizz Air|Volaris|Copa|Aeromexico)"
)


def parse_args():
    p = argparse.ArgumentParser(description="Google Flights scraper — any route/dates/class")
    # Route
    p.add_argument("--origin", required=True, help="Origin airport code (e.g. SFO)")
    p.add_argument("--dest", required=True, help="Destination airport code (e.g. BCN)")
    # Dates
    p.add_argument("--out-dates", default=None, help="Comma-separated outbound dates")
    p.add_argument("--ret-dates", default=None, help="Comma-separated return dates")
    p.add_argument("--out-start", default=None, help="Outbound range start (YYYY-MM-DD)")
    p.add_argument("--out-end", default=None, help="Outbound range end")
    p.add_argument("--ret-start", default=None, help="Return range start")
    p.add_argument("--ret-end", default=None, help="Return range end")
    p.add_argument("--date-step", type=int, default=2, help="Days between sampled dates (default: 2)")
    p.add_argument("--one-way", action="store_true", help="One-way search")
    # Filters
    p.add_argument("--cabin", default="economy", choices=["economy", "premium economy", "business", "first"])
    p.add_argument("--airlines", default=None, help="Comma-separated airline filter (default: all)")
    p.add_argument("--min-stay", type=int, default=0)
    p.add_argument("--max-stay", type=int, default=999)
    # Output
    p.add_argument("--csv", default=None)
    p.add_argument("--html", default=None)
    p.add_argument("--json-out", default=None)
    # Country / proxy — for geo-pricing comparison
    p.add_argument("--country", default="US", choices=list(COUNTRY_PRESETS.keys()),
                   help="Browse as if from this country (sets locale, timezone, currency)")
    p.add_argument("--proxy", default=None,
                   help="HTTP/SOCKS5 proxy (e.g. socks5://1.2.3.4:1080 or http://user:pass@proxy:8080)")
    p.add_argument("--currency", default=None,
                   help="Override currency (e.g. EUR, GBP). Default: from --country")
    # Browser
    p.add_argument("--headed", action="store_true")
    p.add_argument("--delay-min", type=float, default=5)
    p.add_argument("--delay-max", type=float, default=10)
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def human_delay(lo=3, hi=7):
    time.sleep(random.uniform(lo, hi))


def click_el(page, locator):
    el = locator.first
    box = el.bounding_box()
    if box and box["width"] > 0:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        return True
    return False


def apply_airline_filter(page, airline_names):
    """
    Click the Airlines filter on Google Flights and select ONLY the specified airlines.
    This is critical — without it, Google only shows its own 'Best' picks.
    """
    try:
        # Click the Airlines filter button
        airlines_btn = page.locator('button:has-text("Airlines"), button:has-text("All airlines")')
        if airlines_btn.count() == 0:
            return False
        click_el(page, airlines_btn)
        human_delay(1, 2)

        # Look for "Select all" or individual airline checkboxes
        # First try to clear all selections
        for clear_text in ["Clear airline selections", "Reset"]:
            try:
                clear = page.locator(f'a:has-text("{clear_text}"), button:has-text("{clear_text}"), span:has-text("{clear_text}")')
                if clear.count() > 0:
                    click_el(page, clear)
                    human_delay(0.5, 1)
                    break
            except:
                pass

        # Select each target airline
        selected = 0
        for name in airline_names:
            # Try different label patterns Google uses
            for selector in [
                f'label:has-text("{name}")',
                f'div[role="checkbox"]:has-text("{name}")',
                f'li:has-text("{name}")',
                f'span:has-text("{name}")',
            ]:
                try:
                    el = page.locator(selector)
                    if el.count() > 0:
                        click_el(page, el)
                        selected += 1
                        human_delay(0.3, 0.6)
                        break
                except:
                    continue

        # Close the filter dropdown
        human_delay(0.5, 1)
        try:
            close = page.locator('button:has-text("Close"), button[aria-label="Close"]')
            if close.count() > 0:
                click_el(page, close)
            else:
                page.keyboard.press("Escape")
        except:
            page.keyboard.press("Escape")

        human_delay(2, 4)  # Wait for results to update with filter
        return selected > 0

    except Exception as e:
        # If filter fails, continue without it
        try:
            page.keyboard.press("Escape")
        except:
            pass
        return False


def apply_stops_filter(page, max_stops=1):
    """Click the Stops filter and select max stops."""
    try:
        stops_btn = page.locator('button:has-text("Stops"), button:has-text("stops")')
        if stops_btn.count() == 0:
            return
        click_el(page, stops_btn)
        human_delay(0.5, 1)

        if max_stops == 0:
            target = page.locator('label:has-text("Nonstop only"), li:has-text("Nonstop only")')
        else:
            target = page.locator('label:has-text("1 stop or fewer"), li:has-text("1 stop or fewer")')

        if target.count() > 0:
            click_el(page, target)
            human_delay(0.5, 1)

        try:
            close = page.locator('button:has-text("Close"), button[aria-label="Close"]')
            if close.count() > 0:
                click_el(page, close)
            else:
                page.keyboard.press("Escape")
        except:
            page.keyboard.press("Escape")

        human_delay(1, 2)
    except:
        try:
            page.keyboard.press("Escape")
        except:
            pass


def search_roundtrip(page, origin, dest, out_date, ret_date, cabin, one_way=False,
                     domain="google.com", currency="USD", debug=False,
                     filter_airlines=None, max_stops=1):
    """
    Search flights on Google Flights:
    1. Load URL with route + dates + class
    2. Apply airline filter (only show target airlines)
    3. Apply stops filter (direct or 1 stop)
    4. Extract filtered results
    """
    if one_way or not ret_date:
        q = f"Flights from {origin} to {dest} on {out_date} one way {cabin} class"
    else:
        q = f"Flights from {origin} to {dest} on {out_date} returning {ret_date} {cabin} class"
    url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}&curr={currency}&hl=en"
    page.goto(url, timeout=45000)
    human_delay(6, 10)

    # Apply airline filter FIRST — this makes Google show only our target airlines
    if filter_airlines:
        applied = apply_airline_filter(page, filter_airlines)
        if applied:
            human_delay(2, 3)  # Wait for results to refresh

    # Apply stops filter
    apply_stops_filter(page, max_stops)

    # Scroll to load results
    page.mouse.wheel(0, 500)
    human_delay(2, 3)

    # Expand "Other flights" to see more options
    try:
        for txt in ["more flights", "View more", "Other flights", "Show more"]:
            more = page.locator(f'button:has-text("{txt}")')
            if more.count() > 0:
                click_el(page, more)
                human_delay(2, 3)
                break
    except:
        pass

    page.mouse.wheel(0, 500)
    human_delay(1, 2)

    results = []

    # Google Flights uses li elements in US, but proxy/locale may use different layouts
    # Try multiple container selectors
    items = page.locator("li, [role='listitem'], [class*='Rk10dc']").all()
    for item in items:
        text = item.inner_text().strip()
        # Match prices in any currency: $1,234 or 1.234 € or £1,234 or 1 234 €
        # \xa0 is non-breaking space used in European formatting
        if not re.search(r"[$€£]\s*[\d.,\xa0]+|[\d.,\xa0]+\s*[$€£]|[\d.,]+\s*(?:USD|EUR|GBP)", text):
            continue
        if len(text) < 30 or len(text) > 800:
            continue

        # Only take the first airline — Google lists operating carrier first
        all_airlines_found = AIRLINE_PATTERN.findall(text)
        if not all_airlines_found:
            continue
        airlines = all_airlines_found[:1]  # Primary operating carrier only

        # Extract price — handle multiple formats:
        # US: $5,274  |  EUR: €4.831 or 4.831 € or 4 831 €  |  UK: £3,200
        price_m = (
            re.search(r"[$€£]\s*([\d.,\xa0]+)", text)
            or re.search(r"([\d.,\xa0]+)\s*[$€£]", text)
            or re.search(r"([\d.,]+)\s*(?:USD|EUR|GBP)", text)
        )
        if not price_m:
            continue
        price_str = price_m.group(1).replace("\xa0", "").strip()
        # Handle European number format (1.234,56 → 1234.56) vs US (1,234.56)
        if "." in price_str and "," in price_str:
            if price_str.rindex(",") > price_str.rindex("."):
                price_str = price_str.replace(".", "").replace(",", ".")
            else:
                price_str = price_str.replace(",", "")
        elif "." in price_str and price_str.count(".") > 1:
            # Multiple dots: 1.234.567 → European thousands separator
            price_str = price_str.replace(".", "")
        elif "." in price_str and len(price_str.split(".")[-1]) == 3:
            # Single dot as thousands: 5.274 → 5274
            price_str = price_str.replace(".", "")
        else:
            price_str = price_str.replace(",", "")
        try:
            price = int(float(price_str))
        except ValueError:
            continue
        if price < 30 or price > 100000:
            continue

        # Extract times (there will be 4 for round-trip: dep1, arr1, dep2, arr2)
        times = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)", text)

        # Extract durations (2 for round-trip)
        durations = re.findall(r"\d+\s*hr\s*(?:\d+\s*min)?", text)

        # Stops
        stop_texts = re.findall(r"Nonstop|\d+\s*stop", text, re.I)

        # Airline - for codeshares like "UnitedLufthansa" in the raw text
        airline_str = ", ".join(dict.fromkeys(airlines))  # dedupe preserving order

        # Check for "UnitedLufthansa" pattern (Google merges them)
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
            "raw_text": text[:300],
        })

    # Fallback: if no results from li scanning, try parsing the full page body
    if not results:
        body = page.inner_text("body")
        # Look for blocks containing both an airline name and a price
        # Split body by newlines and look for price lines near airline lines
        lines = body.split("\n")
        for i, line in enumerate(lines):
            line = line.strip()
            price_m = re.search(r"[$€£]\s*([\d.,\xa0]+)|([\d.,\xa0]+)\s*[$€£]", line)
            if not price_m:
                continue
            raw = (price_m.group(1) or price_m.group(2)).replace("\xa0", "").replace(",", "")
            # Handle European dot-as-thousands: €4.066 -> 4066
            if "." in raw and len(raw.split(".")[-1]) == 3:
                raw = raw.replace(".", "")
            elif "." in raw and raw.count(".") > 1:
                raw = raw.replace(".", "")
            try:
                price = int(float(raw))
            except ValueError:
                continue
            if price < 100 or price > 100000:
                continue

            # Search surrounding lines for airline name
            context = " ".join(lines[max(0, i - 5):i + 3])
            airlines = AIRLINE_PATTERN.findall(context)
            if not airlines:
                continue

            airline_str = ", ".join(dict.fromkeys(airlines))
            merged = re.findall(r"([A-Z][a-z]+(?:[A-Z][a-z]+)+)", context)
            for m in merged:
                parts = re.findall(r"[A-Z][a-z]+", m)
                if len(parts) >= 2:
                    airline_str = ", ".join(parts)
                    break

            times = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)", context)
            durations = re.findall(r"\d+\s*hr\s*(?:\d+\s*min)?", context)
            stop_texts = re.findall(r"Nonstop|\d+\s*stop", context, re.I)

            results.append({
                "airline": airline_str,
                "total_price": price,
                "out_departure": times[0] if times else "",
                "out_arrival": times[1] if len(times) > 1 else "",
                "ret_departure": times[2] if len(times) > 2 else "",
                "ret_arrival": times[3] if len(times) > 3 else "",
                "out_duration": durations[0] if durations else "",
                "ret_duration": durations[1] if len(durations) > 1 else "",
                "out_stops": stop_texts[0] if stop_texts else "",
                "ret_stops": stop_texts[1] if len(stop_texts) > 1 else "",
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


def generate_date_pairs(out_dates, ret_dates, min_stay, max_stay):
    """Generate valid (out, ret) pairs within stay constraints."""
    pairs = []
    for od in out_dates:
        odt = datetime.strptime(od, "%Y-%m-%d")
        for rd in ret_dates:
            rdt = datetime.strptime(rd, "%Y-%m-%d")
            stay = (rdt - odt).days
            if min_stay <= stay <= max_stay:
                pairs.append((od, rd, stay))
    return pairs


def generate_dates(start_str, end_str, step=2):
    """Generate date list from start to end with given step."""
    dates = []
    current = datetime.strptime(start_str, "%Y-%m-%d")
    end = datetime.strptime(end_str, "%Y-%m-%d")
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=step)
    return dates


def main():
    args = parse_args()
    DATA_DIR.mkdir(exist_ok=True)
    VAULT_FLIGHTS.mkdir(parents=True, exist_ok=True)

    slug = f"{args.origin.lower()}-{args.dest.lower()}"
    country_suffix = f"-{args.country.lower()}" if args.country != "US" else ""

    # Resolve output paths — append country code for non-US searches
    csv_path = args.csv or str(VAULT_FLIGHTS / f"{slug}{country_suffix}-roundtrip.csv")
    html_path = args.html or str(VAULT_FLIGHTS / f"{slug}{country_suffix}-report.html")
    json_path = args.json_out or str(DATA_DIR / f"{slug}{country_suffix}_results.json")

    # Build date lists
    if args.out_dates:
        out_dates = [d.strip() for d in args.out_dates.split(",")]
    elif args.out_start and args.out_end:
        out_dates = generate_dates(args.out_start, args.out_end, args.date_step)
    else:
        print("ERROR: Provide --out-dates or --out-start/--out-end", file=sys.stderr)
        sys.exit(1)

    if args.one_way:
        ret_dates = [None]
    elif args.ret_dates:
        ret_dates = [d.strip() for d in args.ret_dates.split(",")]
    elif args.ret_start and args.ret_end:
        ret_dates = generate_dates(args.ret_start, args.ret_end, args.date_step)
    else:
        print("ERROR: Provide --ret-dates, --ret-start/--ret-end, or --one-way", file=sys.stderr)
        sys.exit(1)

    # Build search pairs
    if args.one_way:
        pairs = [(od, None, 0) for od in out_dates]
    else:
        pairs = generate_date_pairs(out_dates, ret_dates, args.min_stay, args.max_stay)

    trip_type = "one-way" if args.one_way else "round-trip"
    print(f"Outbound dates: {len(out_dates)}")
    if not args.one_way:
        print(f"Return dates: {len(ret_dates)}")
    print(f"Valid pairs ({trip_type}, stay {args.min_stay}-{args.max_stay}d): {len(pairs)}")

    if not pairs:
        print("No valid date pairs! Check date ranges and stay constraints.")
        return

    # For efficiency: instead of searching every pair individually,
    # Google Flights RT search shows the TOTAL price for a specific pair.
    # We need one search per pair. To reduce volume:
    # 1. First pass: sample every 3rd pair to identify price landscape
    # 2. Second pass: fill in around the cheapest combos
    # But for now, let's just search all pairs (each takes ~10s)

    all_results = []
    airlines_filter = set(a.strip() for a in args.airlines.split(",")) if args.airlines else None
    bd_request_count = 0
    bd_cost_per_request = 0.003  # ~$0.003 per Web Unlocker request

    # Country settings
    country = COUNTRY_PRESETS[args.country]
    currency = args.currency or country["currency"]
    domain = country["domain"]
    currency_symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency, currency + " ")

    # For non-US countries, try Bright Data Web Unlocker instead of proxy
    use_brightdata = False
    bd_api_key = None
    if args.country != "US" and not args.proxy:
        try:
            from brightdata import get_api_key, search_from_country, CURRENCY_MAP
            bd_api_key = get_api_key()
            if bd_api_key:
                use_brightdata = True
                print(f"Using Bright Data Web Unlocker for {args.country.upper()} pricing (~$0.003/request)")
            else:
                print("No Bright Data API key — run: python brightdata.py --setup YOUR_KEY")
                print("Searching with US IP but EU locale/currency")
        except ImportError:
            print("brightdata.py not available — searching without geo-pricing")

    # === Bright Data path (non-US countries) ===
    if use_brightdata:
        from brightdata import search_from_country, CURRENCY_MAP
        bd_currency = CURRENCY_MAP.get(args.country.lower(), "USD")

        for i, (out_date, ret_date, stay) in enumerate(pairs):
            if args.one_way:
                print(f"[{i+1}/{len(pairs)}] {out_date}...", end=" ", flush=True)
            else:
                print(f"[{i+1}/{len(pairs)}] {out_date} → {ret_date} ({stay}d)...", end=" ", flush=True)

            try:
                flights = search_from_country(
                    args.origin, args.dest, out_date, ret_date,
                    args.cabin, args.country, args.one_way, bd_api_key
                )
                bd_request_count += 1
            except Exception as e:
                print(f"ERROR: {str(e)[:60]}")
                continue

            if airlines_filter:
                interesting = [f for f in flights
                               if any(a.lower() in f["airline"].lower() for a in airlines_filter)]
            else:
                interesting = flights

            if interesting:
                best = min(interesting, key=lambda x: x["total_price"])
                print(f"{len(interesting)} matches, best: {best['airline']} {currency_symbol}{best['total_price']:,}")
            else:
                print(f"{len(flights)} flights, 0 matches")

            for f in interesting:
                all_results.append({
                    "airline": f["airline"],
                    "class": args.cabin,
                    "outbound_date": out_date,
                    "return_date": ret_date or "",
                    "stay_days": stay,
                    "out_departure": f.get("out_departure", ""),
                    "out_arrival": f.get("out_arrival", ""),
                    "out_duration": f.get("out_duration", ""),
                    "out_stops": f.get("out_stops", ""),
                    "ret_departure": f.get("ret_departure", ""),
                    "ret_arrival": f.get("ret_arrival", ""),
                    "ret_duration": f.get("ret_duration", ""),
                    "ret_stops": f.get("ret_stops", ""),
                    "total_price": f"{currency_symbol}{f['total_price']:,}",
                    "total_price_num": f["total_price"],
                    "currency": currency,
                    "country": args.country,
                    "search_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })

            human_delay(2, 5)  # Lighter delays for API calls

        # Skip Playwright section
        all_results.sort(key=lambda x: x["total_price_num"])
        bd_total_cost = bd_request_count * bd_cost_per_request
        print(f"\nBright Data: {bd_request_count} requests, estimated cost: ${bd_total_cost:.3f}")

        # Jump to output
        Path(json_path).write_text(json.dumps(all_results, indent=2, default=str))
        print(f"JSON: {json_path}")

        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        for r in all_results:
            r["out_flight"] = r["airline"]
            r["ret_flight"] = r["airline"]
            r["out_price"] = "RT"
            r["ret_price"] = "RT"
            r["out_price_num"] = r["total_price_num"] if args.one_way else r["total_price_num"] / 2
            r["ret_price_num"] = 0 if args.one_way else r["total_price_num"] / 2
            r["bd_cost"] = f"${bd_total_cost:.3f}"

        fields_full = [
            "airline", "class", "outbound_date", "return_date", "stay_days",
            "out_flight", "out_departure", "out_arrival", "out_duration", "out_stops", "out_price",
            "ret_flight", "ret_departure", "ret_arrival", "ret_duration", "ret_stops", "ret_price",
            "total_price", "search_date",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            import csv as csv_mod
            writer = csv_mod.DictWriter(f, fieldnames=fields_full, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_results)
        print(f"CSV: {csv_path} ({len(all_results)} rows)")

        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from generate_report import generate_report
            generate_report(csv_path, html_path)
        except Exception as e:
            print(f"Report: {e}")

        # Summary
        print(f"\n{'='*60}")
        print(f"TOP 20 CHEAPEST (from {args.country.upper()}, {currency})")
        print(f"{'='*60}")
        seen = set()
        rank = 0
        for r in all_results:
            key = (r["airline"], r["total_price_num"], r["outbound_date"], r.get("return_date", ""))
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            if rank > 20:
                break
            print(f"  {rank:2d}. {r['airline']:<30s} {r['total_price']:>10s}  "
                  f"{r['outbound_date']}→{r.get('return_date','')} ({r['stay_days']}d)")

        print(f"\nBright Data cost: ${bd_total_cost:.3f} ({bd_request_count} requests)")
        return

    # === Playwright path (US or with proxy) ===
    with sync_playwright() as pw:
        launch_opts = {
            "headless": not args.headed,
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        }
        if args.proxy:
            launch_opts["proxy"] = {"server": args.proxy}

        browser = pw.chromium.launch(**launch_opts)
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale=country["locale"],
            timezone_id=country["tz"],
            geolocation=country["geo"],
            permissions=["geolocation"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        ctx.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
        page = ctx.new_page()

        print(f"\n{'='*60}")
        print(f"  {trip_type}: {args.origin} {'→' if args.one_way else '↔'} {args.dest} | {args.cabin}")
        print(f"  {len(pairs)} searches | airlines: {airlines_filter or 'all'}")
        print(f"  Country: {args.country} | Currency: {currency} | Domain: {domain}")
        if args.proxy:
            print(f"  Proxy: {args.proxy}")
        print(f"{'='*60}\n")

        for i, (out_date, ret_date, stay) in enumerate(pairs):
            if args.one_way:
                print(f"[{i+1}/{len(pairs)}] {out_date}...", end=" ", flush=True)
            else:
                print(f"[{i+1}/{len(pairs)}] {out_date} → {ret_date} ({stay}d)...", end=" ", flush=True)

            flights = search_roundtrip(page, args.origin, args.dest, out_date, ret_date, args.cabin, args.one_way, domain, currency, args.debug, filter_airlines=list(airlines_filter) if airlines_filter else None)

            # Filter to airlines of interest
            if airlines_filter:
                interesting = []
                for f in flights:
                    airline_lower = f["airline"].lower()
                    if any(a.lower() in airline_lower for a in airlines_filter):
                        interesting.append(f)
            else:
                interesting = flights

            if interesting:
                best = min(interesting, key=lambda x: x["total_price"])
                print(f"{len(interesting)} matches, best: {best['airline']} {currency_symbol}{best['total_price']:,}")
            else:
                print(f"{len(flights)} flights, 0 matches")

            for f in interesting:
                all_results.append({
                    "airline": f["airline"],
                    "class": args.cabin,
                    "outbound_date": out_date,
                    "return_date": ret_date,
                    "stay_days": stay,
                    "out_departure": f["out_departure"],
                    "out_arrival": f["out_arrival"],
                    "out_duration": f["out_duration"],
                    "out_stops": f["out_stops"],
                    "ret_departure": f["ret_departure"],
                    "ret_arrival": f["ret_arrival"],
                    "ret_duration": f["ret_duration"],
                    "ret_stops": f["ret_stops"],
                    "total_price": f"{currency_symbol}{f['total_price']:,}",
                    "total_price_num": f["total_price"],
                    "currency": currency,
                    "country": args.country,
                    "search_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })

            # Delays
            if (i + 1) % 10 == 0:
                print("  (longer pause)")
                human_delay(15, 30)
            else:
                human_delay(5, 10)

        browser.close()

    # Sort by price
    all_results.sort(key=lambda x: x["total_price_num"])

    # === Auto Spain price comparison (for US searches) ===
    spain_data = None
    if args.country == "US" and not args.one_way and all_results:
        try:
            from brightdata import search_from_country as bd_search, get_api_key as bd_get_key
            bd_key = bd_get_key()
            if bd_key:
                seen_pairs = set()
                top_for_spain = []
                for r in all_results:
                    pk = (r.get("outbound_date"), r.get("return_date"))
                    if pk in seen_pairs or not pk[0] or not pk[1]:
                        continue
                    seen_pairs.add(pk)
                    top_for_spain.append(r)
                    if len(top_for_spain) >= 10:
                        break

                print(f"\n{'='*70}")
                print(f"  SPAIN PRICE COMPARISON (top {len(top_for_spain)} US results)")
                print(f"  Via Bright Data Web Unlocker (~$0.003/request)")
                print(f"{'='*70}\n")

                eur_usd = 1.08
                comps = []
                bd_reqs = 0
                for idx, us_r in enumerate(top_for_spain):
                    od, rd = us_r["outbound_date"], us_r["return_date"]
                    print(f"  [{idx+1}/{len(top_for_spain)}] {od} -> {rd}...", end=" ", flush=True)
                    try:
                        es_fl = bd_search(args.origin, args.dest, od, rd, args.cabin, "es", False, bd_key)
                        bd_reqs += 1
                    except Exception as exc:
                        print(f"ERROR: {str(exc)[:40]}")
                        continue
                    es_best = min(es_fl, key=lambda x: x["total_price"]) if es_fl else None
                    us_p = us_r.get("total_price_num", 0)
                    if es_best:
                        es_eur = es_best["total_price"]
                        es_usd = es_eur * eur_usd
                        sav = us_p - es_usd
                        pct = (sav / us_p * 100) if us_p else 0
                        print(f"EUR {es_eur:,} (~${es_usd:,.0f}) savings: ${sav:+,.0f} ({pct:+.0f}%)")
                        comps.append({
                            "outbound_date": od, "return_date": rd,
                            "us_airline": us_r.get("airline", ""), "us_price_usd": us_p,
                            "es_airline": es_best.get("airline", ""), "es_price_eur": es_eur,
                            "es_price_usd": round(es_usd), "savings_usd": round(sav), "savings_pct": round(pct, 1),
                        })
                    else:
                        print("no results")
                    time.sleep(2)

                bd_cost = bd_reqs * 0.003
                spain_data = {"comparisons": comps, "bd_requests": bd_reqs, "bd_cost": bd_cost}
                if comps:
                    avg_s = sum(c["savings_usd"] for c in comps) / len(comps)
                    best_s = max(comps, key=lambda c: c["savings_usd"])
                    print(f"\n  Avg savings from Spain: ${avg_s:+,.0f} | Best: ${best_s['savings_usd']:+,}")
                    print(f"  Bright Data cost: ${bd_cost:.3f} ({bd_reqs} requests)")
        except ImportError:
            pass

    # Save raw JSON (include Spain comparison)
    save_payload = all_results
    if spain_data:
        save_payload = {"results": all_results, "spain_comparison": spain_data}
    Path(json_path).write_text(json.dumps(save_payload, indent=2, default=str))
    print(f"\nJSON: {json_path}")

    # Write CSV
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    fields = [
        "airline", "class", "outbound_date", "return_date", "stay_days",
        "out_departure", "out_arrival", "out_duration", "out_stops",
        "ret_departure", "ret_arrival", "ret_duration", "ret_stops",
        "total_price", "search_date",
    ]
    # Also add out_price/ret_price as "N/A" for compatibility with report
    for r in all_results:
        r["out_flight"] = r["airline"]
        r["ret_flight"] = r["airline"]
        r["out_price"] = "RT"
        r["ret_price"] = "RT"
        r["out_price_num"] = r["total_price_num"] if args.one_way else r["total_price_num"] / 2
        r["ret_price_num"] = 0 if args.one_way else r["total_price_num"] / 2

    fields_full = [
        "airline", "class", "outbound_date", "return_date", "stay_days",
        "out_flight", "out_departure", "out_arrival", "out_duration", "out_stops", "out_price",
        "ret_flight", "ret_departure", "ret_arrival", "ret_duration", "ret_stops", "ret_price",
        "total_price", "search_date",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields_full, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_results)
    print(f"CSV: {csv_path} ({len(all_results)} rows)")

    # Generate HTML report
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from generate_report import generate_report
        generate_report(csv_path, html_path)
    except Exception as e:
        print(f"Report generation: {e}")

    # Summary
    print(f"\n{'='*60}")
    print(f"TOP 20 CHEAPEST {'ONE-WAY' if args.one_way else 'ROUND-TRIP'} FARES")
    print(f"{'='*60}")
    seen_combos = set()
    rank = 0
    for r in all_results:
        key = (r["airline"], r["total_price_num"], r["outbound_date"], r.get("return_date", ""))
        if key in seen_combos:
            continue
        seen_combos.add(key)
        rank += 1
        if rank > 20:
            break
        if args.one_way:
            print(f"  {rank:2d}. {r['airline']:<25s} {r['total_price']:>8s}  "
                  f"{r['outbound_date']}  {r['out_stops']}")
        else:
            print(f"  {rank:2d}. {r['airline']:<25s} {r['total_price']:>8s}  "
                  f"{r['outbound_date']}→{r['return_date']} ({r['stay_days']}d)  "
                  f"{r['out_stops']} / {r['ret_stops']}")


    # Spain comparison table in summary
    if spain_data and spain_data.get("comparisons"):
        comps = spain_data["comparisons"]
        print(f"\n{'='*70}")
        print(f"  US vs SPAIN PRICE COMPARISON")
        print(f"{'='*70}")
        print(f"  {'Dates':<26s} {'US (USD)':>9s} {'ES (EUR)':>9s} {'ES ~USD':>9s} {'Savings':>12s}")
        print(f"  {'-'*66}")
        for c in comps:
            d = f"{c['outbound_date']} -> {c['return_date']}"
            print(f"  {d:<26s} ${c['us_price_usd']:>7,}  EUR{c['es_price_eur']:>6,}  ${c['es_price_usd']:>7,}  ${c['savings_usd']:>+7,} ({c['savings_pct']:+.0f}%)")
        avg = sum(c["savings_usd"] for c in comps) / len(comps)
        print(f"\n  Avg savings: ${avg:+,.0f} | BD cost: ${spain_data['bd_cost']:.3f}")


if __name__ == "__main__":
    main()
