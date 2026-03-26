#!/usr/bin/env python3
"""Compare the same flights from US vs Spain, save screenshots, generate report."""
import sys, os, json, time, re
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPTS_DIR = Path(__file__).parent
VAULT = Path(os.path.expanduser("~/clawd/obsidian-vault/flights"))
SHOTS_DIR = VAULT / "screenshots"
SHOTS_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = json.loads((SCRIPTS_DIR / "gf_data" / "brightdata_creds.json").read_text())["api_key"]

AIRLINE_RE = re.compile(
    r"(United|Tap Air Portugal|LEVEL|Iberia|American|Delta|SWISS|"
    r"British Airways|Air France|KLM|Lufthansa|Alaska|Condor|LOT|Aer Lingus)"
)


def fetch_html(url, country):
    """Fetch a Google Flights page via Bright Data from a specific country."""
    payload = json.dumps({
        "zone": "web_unlocker1",
        "url": url,
        "country": country,
        "format": "raw",
    }).encode()
    req = urllib.request.Request(
        "https://api.brightdata.com/request",
        data=payload,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=60)
    return resp.read().decode("utf-8", errors="replace")


def extract_all_flights(html, currency_char):
    """Extract all flights from HTML regardless of airline."""
    text = re.sub(r"<[^>]+>", "|", html)

    flights = []
    # Split on "round trip" which appears after each price
    segments = text.split("round trip")

    for seg in segments:
        # Find price
        if currency_char == "$":
            pm = re.search(r"\$([\d,]+)", seg)
        else:
            pm = re.search(r"\u20ac\s*([\d.,]+)", seg)
        if not pm:
            continue

        price_str = pm.group(1).replace(",", "")
        if "." in price_str and len(price_str.split(".")[-1]) == 3:
            price_str = price_str.replace(".", "")
        try:
            price = int(float(price_str))
        except ValueError:
            continue
        if price < 500 or price > 50000:
            continue

        airlines = AIRLINE_RE.findall(seg)
        if not airlines:
            continue

        times = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM)", seg)
        stops = re.findall(r"Nonstop|\d+\s*stop", seg, re.I)
        durs = re.findall(r"\d+\s*hr\s*(?:\d+\s*min)?", seg)

        airline = ", ".join(dict.fromkeys(airlines))

        flights.append({
            "airline": airline,
            "price": price,
            "stops": stops[0] if stops else "?",
            "duration": durs[0] if durs else "?",
            "departure": times[0] if times else "",
        })

    # Dedupe
    seen = set()
    unique = []
    for f in flights:
        key = (f["airline"][:25], f["price"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    unique.sort(key=lambda x: x["price"])
    return unique


def screenshot_html(html_content, output_path, label):
    """Render HTML in Playwright and take a screenshot."""
    temp_file = VAULT / f"_temp_{label}.html"
    temp_file.write_text(html_content, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(f"file:///{str(temp_file).replace(os.sep, '/')}")
        time.sleep(3)
        # Scroll down a bit to show flight results
        page.mouse.wheel(0, 200)
        time.sleep(1)
        page.screenshot(path=str(output_path))
        browser.close()

    temp_file.unlink(missing_ok=True)


def main():
    # Date pairs to compare (from our top US results)
    pairs = [
        ("2026-04-30", "2026-07-08"),
        ("2026-04-26", "2026-07-08"),
        ("2026-05-04", "2026-07-08"),
    ]

    all_comparisons = []

    for out_d, ret_d in pairs:
        print(f"\n{'='*70}")
        print(f"  {out_d} -> {ret_d}")
        print(f"{'='*70}")

        q = f"Flights from SFO to BCN on {out_d} returning {ret_d} business class"

        # Fetch from US
        print("  Fetching from US...", end=" ", flush=True)
        us_url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}&curr=USD&hl=en"
        us_html = fetch_html(us_url, "us")
        us_flights = extract_all_flights(us_html, "$")
        print(f"{len(us_flights)} flights")

        # Save HTML and screenshot
        us_html_path = VAULT / f"compare-us-{out_d}.html"
        us_html_path.write_text(us_html, encoding="utf-8")
        us_shot = SHOTS_DIR / f"compare-us-{out_d}.png"
        screenshot_html(us_html, str(us_shot), f"us-{out_d}")

        time.sleep(2)

        # Fetch from Spain
        print("  Fetching from Spain...", end=" ", flush=True)
        es_url = f"https://www.google.com/travel/flights?q={q.replace(' ', '+')}&curr=EUR&hl=en"
        es_html = fetch_html(es_url, "es")
        es_flights = extract_all_flights(es_html, "\u20ac")
        print(f"{len(es_flights)} flights")

        es_html_path = VAULT / f"compare-es-{out_d}.html"
        es_html_path.write_text(es_html, encoding="utf-8")
        es_shot = SHOTS_DIR / f"compare-es-{out_d}.png"
        screenshot_html(es_html, str(es_shot), f"es-{out_d}")

        time.sleep(2)

        # Print comparison
        print(f"\n  {'Airline':<35s} {'US ($)':>10s} {'Spain (€)':>10s} {'Spain (~$)':>10s} {'Diff':>10s}")
        print(f"  {'-'*75}")

        for us_f in us_flights[:8]:
            print(f"  {us_f['airline']:<35s} ${us_f['price']:>8,}{'':>22s}")

        print()
        for es_f in es_flights[:8]:
            approx_usd = round(es_f["price"] * 1.08)
            print(f"  {es_f['airline']:<35s}{'':>12s} EUR{es_f['price']:>7,}  ${approx_usd:>8,}")

        # Match same airlines between US and Spain
        print(f"\n  --- Same-airline matches ---")
        for us_f in us_flights:
            us_airlines_set = set(us_f["airline"].lower().split(", "))
            for es_f in es_flights:
                es_airlines_set = set(es_f["airline"].lower().split(", "))
                if us_airlines_set & es_airlines_set:  # Any overlap
                    es_usd = round(es_f["price"] * 1.08)
                    diff = us_f["price"] - es_usd
                    pct = (diff / us_f["price"] * 100) if us_f["price"] else 0
                    print(f"  {us_f['airline']:<35s} ${us_f['price']:>8,}  EUR{es_f['price']:>7,}  ${es_usd:>8,}  ${diff:>+7,} ({pct:+.0f}%)")

                    all_comparisons.append({
                        "dates": f"{out_d} -> {ret_d}",
                        "airline_us": us_f["airline"],
                        "airline_es": es_f["airline"],
                        "us_price": us_f["price"],
                        "es_price_eur": es_f["price"],
                        "es_price_usd": es_usd,
                        "savings": diff,
                        "pct": round(pct, 1),
                        "us_screenshot": str(us_shot),
                        "es_screenshot": str(es_shot),
                    })
                    break

    # Generate comparison HTML report
    print(f"\n\n{'='*70}")
    print("Generating comparison report...")

    report_path = VAULT / "sfo-bcn-us-vs-spain.html"
    generate_comparison_report(all_comparisons, pairs, report_path)
    print(f"Report: {report_path}")
    print(f"Screenshots: {SHOTS_DIR}")

    # Summary
    if all_comparisons:
        avg = sum(c["savings"] for c in all_comparisons) / len(all_comparisons)
        print(f"\nSame-airline comparisons: {len(all_comparisons)}")
        print(f"Average savings from Spain: ${avg:+,.0f}")
        bd_cost = len(pairs) * 2 * 0.003  # 2 requests per pair (US + ES)
        print(f"Bright Data cost: ${bd_cost:.3f} ({len(pairs)*2} requests)")


def generate_comparison_report(comparisons, pairs, output_path):
    """Generate an HTML report with screenshots and price comparison."""
    import base64

    def img_to_base64(path):
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except:
            return ""

    rows_html = ""
    for c in comparisons:
        color = "#6ee7b7" if c["savings"] > 0 else "#f87171"
        rows_html += f"""
        <tr>
            <td>{c['dates']}</td>
            <td>{c['airline_us']}</td>
            <td class="price">${c['us_price']:,}</td>
            <td class="price">&euro;{c['es_price_eur']:,}</td>
            <td class="price">${c['es_price_usd']:,}</td>
            <td class="price" style="color:{color}">${c['savings']:+,} ({c['pct']:+.1f}%)</td>
        </tr>"""

    screenshots_html = ""
    for out_d, ret_d in pairs:
        us_shot = SHOTS_DIR / f"compare-us-{out_d}.png"
        es_shot = SHOTS_DIR / f"compare-es-{out_d}.png"
        us_b64 = img_to_base64(str(us_shot))
        es_b64 = img_to_base64(str(es_shot))
        screenshots_html += f"""
        <h3>{out_d} &rarr; {ret_d}</h3>
        <div class="screenshots">
            <div class="shot">
                <h4>US Pricing (USD)</h4>
                <img src="data:image/png;base64,{us_b64}" alt="US pricing">
            </div>
            <div class="shot">
                <h4>Spain Pricing (EUR)</h4>
                <img src="data:image/png;base64,{es_b64}" alt="Spain pricing">
            </div>
        </div>"""

    avg_savings = sum(c["savings"] for c in comparisons) / len(comparisons) if comparisons else 0

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SFO-BCN: US vs Spain Price Comparison</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }}
h1 {{ color: #f1f5f9; }} h2,h3 {{ color: #94a3b8; margin-top: 30px; }}
.summary {{ background: linear-gradient(135deg, #065f46, #064e3b); border-radius: 10px; padding: 20px; margin: 20px 0; }}
.summary .big {{ font-size: 2rem; font-weight: 700; color: #6ee7b7; }}
table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
th {{ background: #1e293b; color: #94a3b8; padding: 10px; text-align: left; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #1e293b; }}
.price {{ font-weight: 600; font-family: monospace; }}
.screenshots {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0; }}
.shot {{ background: #1e293b; border-radius: 8px; padding: 10px; }}
.shot h4 {{ color: #94a3b8; margin: 0 0 10px; }}
.shot img {{ width: 100%; border-radius: 5px; }}
.note {{ color: #64748b; font-size: 0.85rem; margin: 10px 0; }}
</style></head><body>
<h1>SFO &harr; BCN: US vs Spain Pricing</h1>
<p class="note">Generated {time.strftime('%B %d, %Y at %I:%M %p')} | Business class round-trip | Via Bright Data Web Unlocker</p>

<div class="summary">
<div class="big">${avg_savings:+,.0f} average savings</div>
<p>buying from a Spanish IP vs US IP on Google Flights</p>
</div>

<h2>Price Comparison Table</h2>
<table>
<tr><th>Dates</th><th>Airline</th><th>US (USD)</th><th>Spain (EUR)</th><th>Spain (~USD)</th><th>Savings</th></tr>
{rows_html}
</table>

<h2>Google Flights Screenshots</h2>
<p class="note">Side-by-side screenshots of the actual Google Flights pages from US and Spain IP addresses.</p>
{screenshots_html}

<h2>Notes</h2>
<ul>
<li>Prices shown are what Google Flights displays from each country's IP</li>
<li>EUR to USD conversion uses approximate rate of 1.08</li>
<li>Spain search uses Bright Data Web Unlocker (~$0.003/request)</li>
<li>The same flight can have different pricing based on country of purchase</li>
<li>Always verify final price on the airline's website before booking</li>
</ul>
</body></html>"""

    output_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
