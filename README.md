# Flight Search

Google Flights scraper with price tracking — finds the cheapest round-trip or one-way fares for any route using headless browser automation.

## Features

- **Any route**: Works with any origin/destination airport codes
- **Round-trip or one-way**: Searches actual bookable fares (round-trip fares are significantly cheaper than 2x one-way)
- **Date range scanning**: Samples dates across a range to find the cheapest departure/return dates
- **Airline filtering**: Filter results by specific airlines
- **Cabin class**: Economy, premium economy, business, first
- **Price tracking**: Run periodically to track price changes over time
- **HTML reports**: Interactive reports with sortable tables, heatmaps, and charts
- **Anti-detection**: Human-like delays, stealth browser settings

## Requirements

- Python 3.11+
- Playwright (`pip install playwright && python -m playwright install chromium`)

## Quick Start

```bash
# Search round-trip flights
python scripts/gf_roundtrip.py \
  --origin SFO --dest BCN \
  --out-start 2026-04-20 --out-end 2026-05-16 \
  --ret-start 2026-06-28 --ret-end 2026-07-22 \
  --cabin business --airlines "United,TAP"

# One-way search
python scripts/gf_roundtrip.py \
  --origin JFK --dest LHR \
  --out-dates 2026-06-15 \
  --one-way --cabin economy
```

## OpenClaw Skill

This project doubles as an OpenClaw skill. Symlink or copy to your skills directory:

```bash
ln -s "/path/to/flight-search" ~/.openclaw/skills/flight-search
# or
ln -s "/path/to/flight-search" ~/clawd/skills/flight-search
```

## Price Tracking

The tracker saves each run and compares prices between runs:

```bash
# Run tracking (called by cron every 12 hours)
python scripts/track_prices.py

# View price history
python scripts/track_prices.py --history

# Compare last two runs
python scripts/track_prices.py --compare

# Stop tracking (flight purchased)
python scripts/track_prices.py --stop
```

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | OpenClaw skill metadata |
| `scripts/gf_roundtrip.py` | Main scraper — any route/dates/class |
| `scripts/track_prices.py` | Price tracker with historical comparison |
| `scripts/generate_report.py` | HTML report generator |
| `scripts/scrape_level.py` | FlyLevel direct API scraper |
| `scripts/search_flights.py` | Legacy fast-flights based search |

## License

MIT
