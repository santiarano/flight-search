#!/usr/bin/env python3
"""
Auto-find a working Spanish/EU proxy for flight price geo-checks.
Tests proxies from multiple free sources and saves the best working one.

Usage:
    python find_proxy.py                # Find and save a working proxy
    python find_proxy.py --test         # Test the saved proxy
    python find_proxy.py --country ES   # Find proxy for specific country
"""
import sys, os, json, time, argparse
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import urllib.request

SCRIPTS_DIR = Path(__file__).parent
PROXY_CACHE = SCRIPTS_DIR / "gf_data" / "proxy_cache.json"


def fetch_proxies(countries=("ES", "PT", "FR", "DE", "IT")):
    """Fetch proxy candidates from multiple free sources."""
    proxies = []

    # Source 1: ProxyScrape
    for country in countries:
        for proto in ["http", "socks5"]:
            try:
                url = (
                    f"https://api.proxyscrape.com/v4/free-proxy-list/get?"
                    f"request=display_proxies&country={country.lower()}&protocol={proto}"
                    f"&proxy_format=protocolipport&format=text&timeout=5000"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=10)
                for line in resp.read().decode().strip().split("\n"):
                    line = line.strip()
                    if line and ":" in line:
                        proxies.append({"url": line, "country": country, "source": "proxyscrape"})
            except:
                pass

    # Source 2: GeoNode
    for country in countries:
        try:
            url = (
                f"https://proxylist.geonode.com/api/proxy-list?"
                f"country={country}&limit=10&page=1&sort_by=lastChecked&sort_type=desc"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            for p in data.get("data", []):
                ip, port = p["ip"], p["port"]
                proto = p.get("protocols", ["http"])[0]
                proxies.append({
                    "url": f"{proto}://{ip}:{port}",
                    "country": country,
                    "source": "geonode",
                })
        except:
            pass

    return proxies


def test_proxy(proxy_url, timeout=15):
    """Test a proxy with Playwright — verify it loads Google Flights."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright not installed"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox"],
                proxy={"server": proxy_url},
            )
            page = browser.new_page()

            # Test 1: Basic connectivity
            page.goto("https://httpbin.org/ip", timeout=timeout * 1000)
            ip_info = page.inner_text("body").strip()

            # Test 2: Google Flights loads
            page.goto(
                "https://www.google.com/travel/flights?hl=en&curr=EUR",
                timeout=timeout * 1000,
            )
            time.sleep(3)
            title = page.title()

            browser.close()

            if "Flights" in title or "flights" in title.lower():
                return True, ip_info
            return False, f"title={title}"

    except Exception as e:
        return False, str(e)[:80]


def find_working_proxy(countries=("ES", "PT", "FR", "DE"), max_tests=15):
    """Find a working proxy, test it, return the best one."""
    print("Fetching proxy lists...")
    candidates = fetch_proxies(countries)
    print(f"Found {len(candidates)} candidates across {', '.join(countries)}")

    if not candidates:
        return None

    working = []
    for i, px in enumerate(candidates[:max_tests]):
        print(f"  [{i+1}/{min(len(candidates), max_tests)}] {px['country']} {px['url']}...", end=" ", flush=True)
        ok, info = test_proxy(px["url"])
        if ok:
            print(f"OK! ({info[:40]})")
            working.append({**px, "ip_info": info, "tested": time.time()})
            if len(working) >= 3:
                break
        else:
            print(f"FAIL")

    return working


def load_cached_proxy():
    """Load cached proxy if still fresh (< 6 hours old)."""
    if not PROXY_CACHE.exists():
        return None
    try:
        data = json.loads(PROXY_CACHE.read_text())
        if time.time() - data.get("tested", 0) < 21600:  # 6 hours
            return data.get("proxy")
    except:
        pass
    return None


def save_proxy(proxy_url, country, ip_info):
    """Save working proxy to cache."""
    PROXY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PROXY_CACHE.write_text(json.dumps({
        "proxy": proxy_url,
        "country": country,
        "ip_info": ip_info,
        "tested": time.time(),
    }, indent=2))


def get_proxy(countries=("ES", "PT", "FR", "DE")):
    """Get a working proxy — from cache or find a new one."""
    cached = load_cached_proxy()
    if cached:
        # Quick re-test
        ok, info = test_proxy(cached, timeout=10)
        if ok:
            return cached
        print("Cached proxy no longer working, finding new one...")

    working = find_working_proxy(countries)
    if working:
        best = working[0]
        save_proxy(best["url"], best["country"], best.get("ip_info", ""))
        return best["url"]
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true", help="Test saved proxy")
    p.add_argument("--country", default="ES,PT,FR,DE", help="Countries to search")
    args = p.parse_args()

    PROXY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    countries = tuple(c.strip() for c in args.country.split(","))

    if args.test:
        cached = load_cached_proxy()
        if cached:
            print(f"Testing cached proxy: {cached}")
            ok, info = test_proxy(cached)
            print(f"Result: {'OK' if ok else 'FAIL'} — {info}")
        else:
            print("No cached proxy found.")
        return

    proxy = get_proxy(countries)
    if proxy:
        print(f"\nWorking proxy: {proxy}")
        print(f"Saved to: {PROXY_CACHE}")
        print(f"\nUse with: python gf_roundtrip.py --country ES --proxy {proxy}")
    else:
        print("\nNo working proxy found. Options:")
        print("  1. Try again later (free proxies are ephemeral)")
        print("  2. Use a paid proxy service (Bright Data, Oxylabs)")
        print("  3. Use a VPN with Spanish exit node")
        print("  4. Rent a cheap Spanish VPS (~$3/mo) and run the scraper there")


if __name__ == "__main__":
    main()
