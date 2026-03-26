#!/usr/bin/env python3
"""
Bright Data Web Unlocker integration for geo-priced flight searches.
Fetches Google Flights HTML from any country and extracts flight data.

Usage:
    from brightdata import search_from_country
    results = search_from_country("SFO", "BCN", "2026-05-04", "2026-07-08", "business", "es")
"""
import os, re, json, time, random
from pathlib import Path
import urllib.request

SCRIPTS_DIR = Path(__file__).parent
CREDS_FILE = SCRIPTS_DIR / "gf_data" / "brightdata_creds.json"

AIRLINE_PATTERN = re.compile(
    r"(United|Tap Air Portugal|LEVEL|Iberia|American|Delta|"
    r"SWISS|British Airways|Air France|KLM|Lufthansa|LOT|Aer Lingus|Finnair|Turkish|Norse|"
    r"Emirates|Qatar|Etihad|Singapore|Cathay|ANA|JAL|Korean Air|Avianca|LATAM|"
    r"Vueling|Ryanair|easyJet|Norwegian|JetBlue|Southwest|Alaska|Spirit|Frontier|"
    r"Air Canada|WestJet|Condor|Icelandair|SAS|Wizz Air|Volaris|Copa|Aeromexico|"
    r"Alaska|Azores Airlines)"
)

CURRENCY_MAP = {
    "es": "EUR", "fr": "EUR", "de": "EUR", "it": "EUR", "pt": "EUR",
    "gb": "GBP", "uk": "GBP",
    "us": "USD",
    "mx": "MXN", "br": "BRL", "jp": "JPY",
}


def get_api_key():
    """Load Bright Data API key from creds file."""
    if CREDS_FILE.exists():
        data = json.loads(CREDS_FILE.read_text())
        return data.get("api_key")
    return None


def save_api_key(api_key):
    """Save Bright Data API key."""
    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(json.dumps({"api_key": api_key}))


def fetch_flights_html(origin, dest, out_date, ret_date, cabin, country_code="es",
                       one_way=False, api_key=None):
    """
    Fetch Google Flights HTML via Bright Data Web Unlocker from a specific country.
    Returns the raw HTML string.
    """
    api_key = api_key or get_api_key()
    if not api_key:
        raise ValueError("No Bright Data API key. Run: python brightdata.py --setup YOUR_KEY")

    currency = CURRENCY_MAP.get(country_code.lower(), "USD")

    if one_way or not ret_date:
        q = f"Flights from {origin} to {dest} on {out_date} one way {cabin} class"
    else:
        q = f"Flights from {origin} to {dest} on {out_date} returning {ret_date} {cabin} class"

    url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}&curr={currency}&hl=en"

    payload = json.dumps({
        "zone": "web_unlocker1",
        "url": url,
        "country": country_code.lower(),
        "format": "raw",
    }).encode()

    req = urllib.request.Request(
        "https://api.brightdata.com/request",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    resp = urllib.request.urlopen(req, timeout=60)
    return resp.read().decode("utf-8", errors="replace")


def extract_flights_from_html(html, currency="EUR"):
    """
    Extract flight results from Google Flights HTML.
    Returns list of flight dicts.
    """
    results = []
    currency_symbol = {"EUR": "€", "GBP": "£", "USD": "$"}.get(currency, "$")

    # Google Flights embeds flight data in the page
    # We need to parse from the rendered HTML text content
    # Strategy: find price + airline patterns in proximity

    # Extract text blocks that look like flight results
    # Google Flights uses specific data attributes and class patterns
    # Look for blocks between flight separators

    # Method 1: regex-based extraction from HTML
    # Find all price occurrences with surrounding context
    if currency_symbol == "€":
        price_pattern = re.compile(r"€\s*([\d.,]+)")
    elif currency_symbol == "£":
        price_pattern = re.compile(r"£\s*([\d.,]+)")
    else:
        price_pattern = re.compile(r"\$\s*([\d,]+)")

    # Find all prices
    prices_found = price_pattern.findall(html)

    # Find airline mentions near prices
    # Google Flights has structured data - look for flight result containers
    # Each result typically has: airline logo, name, times, duration, stops, price

    # Method 2: Look for structured patterns in the HTML
    # Google Flights uses aria-labels and data attributes for flight info
    time_pattern = re.compile(r"(\d{1,2}:\d{2}\s*(?:AM|PM))")
    duration_pattern = re.compile(r"(\d+\s*hr\s*(?:\d+\s*min)?)")
    stops_pattern = re.compile(r"(Nonstop|\d+\s*stop)")

    # Strip HTML tags once for the whole page
    full_text = re.sub(r"<[^>]+>", "|", html)

    # Find flight blocks by looking for price elements with nearby airline names
    for price_match in price_pattern.finditer(full_text):
        price_str = price_match.group(1).replace(",", "")
        # Handle European format: 4.065 -> 4065
        if "." in price_str and len(price_str.split(".")[-1]) == 3:
            price_str = price_str.replace(".", "")
        try:
            price = int(float(price_str))
        except ValueError:
            continue
        if price < 100 or price > 100000:
            continue

        # Look at surrounding context (5000 chars before the price for airline name)
        start = max(0, price_match.start() - 5000)
        context = full_text[start:price_match.end() + 500]

        # Clean up
        text_context = re.sub(r"\|+", " ", context)
        text_context = re.sub(r"\s+", " ", text_context)

        airlines = AIRLINE_PATTERN.findall(text_context)
        if not airlines:
            continue

        times = time_pattern.findall(text_context)
        durations = duration_pattern.findall(text_context)
        stops = stops_pattern.findall(text_context)

        airline_str = ", ".join(dict.fromkeys(airlines))
        if "Tap Air Portugal" in airline_str:
            airline_str = airline_str.replace("Tap Air Portugal", "TAP Portugal")

        results.append({
            "airline": airline_str,
            "total_price": price,
            "out_departure": times[0] if times else "",
            "out_arrival": times[1] if len(times) > 1 else "",
            "ret_departure": times[2] if len(times) > 2 else "",
            "ret_arrival": times[3] if len(times) > 3 else "",
            "out_duration": durations[0] if durations else "",
            "ret_duration": durations[1] if len(durations) > 1 else "",
            "out_stops": stops[0] if stops else "",
            "ret_stops": stops[1] if len(stops) > 1 else "",
        })

    # Deduplicate
    seen = set()
    unique = []
    for r in results:
        key = (r["airline"], r["total_price"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    unique.sort(key=lambda x: x["total_price"])
    return unique


def search_from_country(origin, dest, out_date, ret_date, cabin, country_code="es",
                        one_way=False, api_key=None):
    """
    Full search: fetch HTML via Bright Data and extract flights.
    Returns list of flight result dicts.
    """
    currency = CURRENCY_MAP.get(country_code.lower(), "USD")
    html = fetch_flights_html(origin, dest, out_date, ret_date, cabin,
                              country_code, one_way, api_key)
    return extract_flights_from_html(html, currency)


if __name__ == "__main__":
    import sys, argparse
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="Bright Data flight search")
    p.add_argument("--setup", default=None, help="Save API key: --setup YOUR_API_KEY")
    p.add_argument("--test", action="store_true", help="Test with sample search")
    p.add_argument("--origin", default="SFO")
    p.add_argument("--dest", default="BCN")
    p.add_argument("--out-date", default="2026-05-04")
    p.add_argument("--ret-date", default="2026-07-08")
    p.add_argument("--cabin", default="business")
    p.add_argument("--country", default="es")
    args = p.parse_args()

    if args.setup:
        save_api_key(args.setup)
        print(f"API key saved to {CREDS_FILE}")
        sys.exit(0)

    if args.test or args.origin:
        api_key = get_api_key()
        if not api_key:
            print("No API key. Run: python brightdata.py --setup YOUR_API_KEY")
            sys.exit(1)

        currency = CURRENCY_MAP.get(args.country.lower(), "USD")
        symbol = {"EUR": "€", "GBP": "£", "USD": "$"}.get(currency, "$")

        print(f"Searching {args.origin}→{args.dest} from {args.country.upper()} ({currency})...")
        flights = search_from_country(
            args.origin, args.dest, args.out_date, args.ret_date,
            args.cabin, args.country, api_key=api_key
        )
        print(f"Found {len(flights)} flights\n")
        for i, f in enumerate(flights[:15], 1):
            print(f"  {i:2d}. {f['airline']:<30s} {symbol}{f['total_price']:,}")
