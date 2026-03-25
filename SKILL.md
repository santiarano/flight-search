---
name: flight-search
description: >
  Search Google Flights for the cheapest round-trip or one-way fares between any airports.
  Uses Playwright headless browser to get accurate, real-time prices.
  Supports any origin/destination, date range, cabin class, and airline filter.
  Generates CSV data and interactive HTML reports with heatmaps and charts.
metadata:
  openclaw:
    emoji: "✈️"
    agent: "main"
    requires:
      anyBins: ["python3", "python"]
---

# Flight Search

Search Google Flights for the cheapest flights between any airports. Uses headless browser automation to get accurate, real-time round-trip or one-way fares.

## Quick Start

```bash
# Round-trip: search date ranges
python skills/flight-search/scripts/gf_roundtrip.py \
  --origin SFO --dest BCN \
  --out-start 2026-04-20 --out-end 2026-05-16 \
  --ret-start 2026-06-28 --ret-end 2026-07-22 \
  --cabin business --airlines "United,TAP"

# Round-trip: specific dates
python skills/flight-search/scripts/gf_roundtrip.py \
  --origin SFO --dest BCN \
  --out-dates 2026-05-12 --ret-dates 2026-07-08 \
  --cabin business

# One-way search
python skills/flight-search/scripts/gf_roundtrip.py \
  --origin SFO --dest BCN \
  --out-start 2026-04-20 --out-end 2026-05-16 \
  --one-way --cabin business

# With visible browser
python skills/flight-search/scripts/gf_roundtrip.py \
  --origin LAX --dest LHR --out-dates 2026-06-15 --ret-dates 2026-06-30 \
  --cabin economy --headed
```

## Parameters

### Required
| Parameter | Description | Example |
|-----------|-------------|---------|
| `--origin` | Origin airport IATA code | `SFO`, `LAX`, `JFK` |
| `--dest` | Destination airport IATA code | `BCN`, `LHR`, `NRT` |

### Dates (provide explicit dates OR start/end ranges)
| Parameter | Description | Example |
|-----------|-------------|---------|
| `--out-dates` | Explicit outbound dates (comma-separated) | `2026-05-01,2026-05-08` |
| `--ret-dates` | Explicit return dates (comma-separated) | `2026-07-01,2026-07-08` |
| `--out-start` / `--out-end` | Outbound date range | `2026-04-20` / `2026-05-16` |
| `--ret-start` / `--ret-end` | Return date range | `2026-06-28` / `2026-07-22` |
| `--date-step` | Days between sampled dates in ranges (default: 2) | `3` |
| `--one-way` | Search one-way (no return dates needed) | flag |

### Filters
| Parameter | Description | Default |
|-----------|-------------|---------|
| `--cabin` | `economy`, `premium economy`, `business`, `first` | `economy` |
| `--airlines` | Comma-separated airline names to filter | all airlines |
| `--min-stay` | Minimum trip duration in days | `0` |
| `--max-stay` | Maximum trip duration in days | `999` |

### Output
| Parameter | Description | Default |
|-----------|-------------|---------|
| `--csv` | CSV output path | `~/clawd/obsidian-vault/flights/{route}-roundtrip.csv` |
| `--html` | HTML report path | `~/clawd/obsidian-vault/flights/{route}-report.html` |
| `--json-out` | Raw JSON output | `scripts/gf_data/{route}_results.json` |

### Browser
| Parameter | Description | Default |
|-----------|-------------|---------|
| `--headed` | Show browser window | headless |
| `--delay-min` | Min delay between searches (seconds) | `5` |
| `--delay-max` | Max delay between searches (seconds) | `10` |

## How It Works

1. Builds date pairs from specified ranges (respecting min/max stay)
2. For each pair, loads Google Flights via natural language URL:
   `google.com/travel/flights?q=Flights from SFO to BCN on 2026-05-12 returning 2026-07-08 business class`
3. Extracts flight results (airline, price, times, duration, stops)
4. Filters by specified airlines (if any)
5. Outputs CSV + interactive HTML report with sortable table, heatmap, and charts

## Runtime Estimates

| Date pairs | Time |
|------------|------|
| 10 | ~2 min |
| 50 | ~10 min |
| 100 | ~20 min |
| 200 | ~40 min |

## Price Tracking & Cron

When the user requests a flight search, create a tracker config and enable the cron:

1. **Create tracker**: Write config to `skills/flight-search/scripts/tracker_data/active_trackers.json`:
```json
{
  "trackers": [{
    "id": "sfo-bcn-202603251200",
    "origin": "SFO", "dest": "BCN",
    "out_start": "2026-04-20", "out_end": "2026-05-16",
    "ret_start": "2026-06-28", "ret_end": "2026-07-22",
    "cabin": "business", "airlines": "United,TAP",
    "min_stay": 60, "max_stay": 75, "date_step": 3,
    "active": true, "runs": []
  }]
}
```

2. **Enable cron**: Set the "Flight price tracker" cron job to `enabled: true` in `~/.openclaw/cron/jobs.json` (job ID: `f1a8c2d0-4e7b-4f9a-b3c1-flight-track01`). It runs at 6 AM and 6 PM PT.

3. **Each run**: The tracker searches all date pairs, saves results, compares with previous run, and reports via Telegram:
   - Price direction (up/down/same)
   - Best current price and dates
   - Biggest price drops and rises

4. **Stop tracking**: When user says they purchased the flight, run:
```bash
python skills/flight-search/scripts/track_prices.py --stop
```
Then set the cron job to `enabled: false`.

## Additional Tools

### FlyLevel Direct API
```bash
python skills/flight-search/scripts/scrape_level.py --monitor
```

### HTML Report Generator
```bash
python skills/flight-search/scripts/generate_report.py --csv PATH --output PATH
```

### Legacy: fast-flights based search (less accurate, faster)
```bash
python skills/flight-search/scripts/search_flights.py --airlines united,tap --mix-airlines
```
