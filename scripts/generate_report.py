#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a self-contained HTML report from flight search CSV data.
Includes sortable table, price heatmap, Chart.js charts, and top deals.

Usage:
    python generate_report.py [--csv PATH] [--output PATH]

Can also be imported: from generate_report import generate_report
"""
import os as _os
_os.environ.setdefault("PYTHONIOENCODING", "utf-8")
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from collections import defaultdict

DEFAULT_CSV = os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-search.csv")
DEFAULT_OUTPUT = os.path.expanduser("~/clawd/obsidian-vault/flights/sfo-bcn-report.html")


def load_csv(csv_path):
    """Load flight data from CSV."""
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse numeric fields
            try:
                row["total_price_num"] = float(row.get("total_price", "$0").replace("$", "").replace(",", ""))
            except (ValueError, AttributeError):
                row["total_price_num"] = float("inf")
            try:
                row["out_price_num"] = float(row.get("out_price", "$0").replace("$", "").replace(",", ""))
            except (ValueError, AttributeError):
                row["out_price_num"] = float("inf")
            try:
                row["ret_price_num"] = float(row.get("ret_price", "$0").replace("$", "").replace(",", ""))
            except (ValueError, AttributeError):
                row["ret_price_num"] = float("inf")
            try:
                row["stay_days"] = int(row.get("stay_days", 0))
            except ValueError:
                row["stay_days"] = 0
            rows.append(row)
    return rows


def compute_stats(rows):
    """Compute summary statistics."""
    if not rows:
        return {}

    airlines = sorted(set(r["airline"] for r in rows))
    best_overall = min(rows, key=lambda r: r["total_price_num"])

    best_by_airline = {}
    for airline in airlines:
        airline_rows = [r for r in rows if r["airline"] == airline]
        if airline_rows:
            best_by_airline[airline] = min(airline_rows, key=lambda r: r["total_price_num"])

    outbound_dates = sorted(set(r["outbound_date"] for r in rows))
    return_dates = sorted(set(r["return_date"] for r in rows))

    return {
        "total_rows": len(rows),
        "airlines": airlines,
        "best_overall": best_overall,
        "best_by_airline": best_by_airline,
        "outbound_dates": outbound_dates,
        "return_dates": return_dates,
        "min_price": min(r["total_price_num"] for r in rows),
        "max_price": max(r["total_price_num"] for r in rows if r["total_price_num"] < float("inf")),
    }


def build_heatmap_data(rows, outbound_dates, return_dates):
    """Build price grid for heatmap (best price per date pair across all airlines)."""
    grid = {}
    for r in rows:
        key = (r["outbound_date"], r["return_date"])
        price = r["total_price_num"]
        if key not in grid or price < grid[key]["price"]:
            grid[key] = {"price": price, "airline": r["airline"]}
    return grid


def build_chart_data(rows):
    """Build data for Chart.js charts."""
    # Cheapest price by outbound date, per airline
    out_by_date = defaultdict(lambda: defaultdict(lambda: float("inf")))
    ret_by_date = defaultdict(lambda: defaultdict(lambda: float("inf")))

    for r in rows:
        price = r["total_price_num"]
        if price < out_by_date[r["outbound_date"]][r["airline"]]:
            out_by_date[r["outbound_date"]][r["airline"]] = price
        if price < ret_by_date[r["return_date"]][r["airline"]]:
            ret_by_date[r["return_date"]][r["airline"]] = price

    return {
        "outbound": dict(out_by_date),
        "return": dict(ret_by_date),
    }


def generate_html(rows, stats, output_path):
    """Generate the full HTML report."""
    heatmap = build_heatmap_data(rows, stats["outbound_dates"], stats["return_dates"])
    chart_data = build_chart_data(rows)

    # Airline colors
    airline_colors = {
        "TAP Portugal": "#00563F",
        "United": "#002244",
        "FlyLevel": "#E31837",
        "TAP Portugal + United": "#4A7C6F",
        "United + TAP Portugal": "#3A5577",
        "TAP Portugal + FlyLevel": "#7A3D3F",
        "United + FlyLevel": "#6A3344",
        "FlyLevel + TAP Portugal": "#E35060",
        "FlyLevel + United": "#E34060",
    }

    # Prepare heatmap JSON
    heatmap_json = {}
    for (out_d, ret_d), data in heatmap.items():
        heatmap_json[f"{out_d}|{ret_d}"] = {"price": data["price"], "airline": data["airline"]}

    # Prepare table data JSON
    table_data = []
    for r in rows:
        table_data.append({
            "airline": r.get("airline", ""),
            "class": r.get("class", ""),
            "outbound_date": r.get("outbound_date", ""),
            "return_date": r.get("return_date", ""),
            "stay_days": r.get("stay_days", 0),
            "out_flight": r.get("out_flight", ""),
            "out_departure": r.get("out_departure", ""),
            "out_duration": r.get("out_duration", ""),
            "out_stops": r.get("out_stops", ""),
            "out_price": r.get("out_price", ""),
            "out_price_num": r.get("out_price_num", 0),
            "ret_flight": r.get("ret_flight", ""),
            "ret_departure": r.get("ret_departure", ""),
            "ret_duration": r.get("ret_duration", ""),
            "ret_stops": r.get("ret_stops", ""),
            "ret_price": r.get("ret_price", ""),
            "ret_price_num": r.get("ret_price_num", 0),
            "total_price": r.get("total_price", ""),
            "total_price_num": r.get("total_price_num", 0),
            "search_date": r.get("search_date", ""),
        })

    # Prepare chart JSON
    airlines = stats["airlines"]
    out_dates_sorted = sorted(chart_data["outbound"].keys())
    ret_dates_sorted = sorted(chart_data["return"].keys())

    out_chart = {"labels": out_dates_sorted, "datasets": []}
    for airline in airlines:
        color = airline_colors.get(airline, "#888888")
        data_points = []
        for d in out_dates_sorted:
            val = chart_data["outbound"].get(d, {}).get(airline, None)
            data_points.append(val if val and val < float("inf") else None)
        out_chart["datasets"].append({"label": airline, "data": data_points, "borderColor": color, "fill": False, "tension": 0.3, "spanGaps": True})

    ret_chart = {"labels": ret_dates_sorted, "datasets": []}
    for airline in airlines:
        color = airline_colors.get(airline, "#888888")
        data_points = []
        for d in ret_dates_sorted:
            val = chart_data["return"].get(d, {}).get(airline, None)
            data_points.append(val if val and val < float("inf") else None)
        ret_chart["datasets"].append({"label": airline, "data": data_points, "borderColor": color, "fill": False, "tension": 0.3, "spanGaps": True})

    best = stats["best_overall"]
    best_by = stats["best_by_airline"]

    # Build summary cards HTML
    summary_cards = f"""
    <div class="card best">
      <div class="card-label">Best Overall</div>
      <div class="card-price">{best['total_price']}</div>
      <div class="card-detail">{best['airline']} &middot; {best['class']}</div>
      <div class="card-detail">{best['outbound_date']} &rarr; {best['return_date']} ({best['stay_days']}d)</div>
    </div>
    """
    for airline, row in best_by.items():
        summary_cards += f"""
    <div class="card">
      <div class="card-label">Best {airline}</div>
      <div class="card-price">{row['total_price']}</div>
      <div class="card-detail">{row['class']}</div>
      <div class="card-detail">{row['outbound_date']} &rarr; {row['return_date']} ({row['stay_days']}d)</div>
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SFO &harr; BCN Flight Search Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 5px; color: #f1f5f9; }}
  h2 {{ font-size: 1.3rem; margin: 30px 0 15px; color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
  .subtitle {{ color: #64748b; margin-bottom: 20px; }}
  .summary {{ display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px; }}
  .card {{ background: #1e293b; border-radius: 10px; padding: 15px 20px; min-width: 200px; flex: 1; }}
  .card.best {{ background: linear-gradient(135deg, #065f46, #064e3b); border: 1px solid #10b981; }}
  .card-label {{ font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
  .card-price {{ font-size: 1.8rem; font-weight: 700; color: #f1f5f9; margin: 5px 0; }}
  .card.best .card-price {{ color: #6ee7b7; }}
  .card-detail {{ font-size: 0.85rem; color: #94a3b8; }}

  /* Filter bar */
  .filters {{ display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; align-items: center; }}
  .filters label {{ color: #94a3b8; font-size: 0.85rem; }}
  .filters select, .filters input {{ background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 5px; padding: 5px 10px; font-size: 0.85rem; }}

  /* Table */
  .table-wrap {{ overflow-x: auto; margin-bottom: 30px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.8rem; }}
  th {{ background: #1e293b; color: #94a3b8; padding: 8px 10px; text-align: left; cursor: pointer; white-space: nowrap; user-select: none; position: sticky; top: 0; }}
  th:hover {{ color: #e2e8f0; }}
  th.sorted-asc::after {{ content: ' \\25B2'; }}
  th.sorted-desc::after {{ content: ' \\25BC'; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #1e293b; white-space: nowrap; }}
  tr:hover {{ background: #1e293b; }}
  tr.top-deal {{ background: #064e3b33; }}
  .price-cell {{ font-weight: 600; }}

  /* Heatmap */
  .heatmap-container {{ overflow-x: auto; margin-bottom: 30px; }}
  .heatmap {{ display: grid; gap: 2px; font-size: 0.65rem; }}
  .heatmap-cell {{ padding: 4px 2px; text-align: center; border-radius: 3px; min-width: 55px; cursor: default; position: relative; }}
  .heatmap-cell:hover {{ outline: 2px solid #f1f5f9; z-index: 1; }}
  .heatmap-header {{ background: #1e293b; color: #94a3b8; font-weight: 600; padding: 6px 2px; }}
  .heatmap-label {{ background: #1e293b; color: #94a3b8; font-weight: 600; padding: 4px 6px; text-align: right; min-width: 85px; }}
  .heatmap-empty {{ background: #0f172a; }}
  .tooltip {{ display: none; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); background: #1e293b; border: 1px solid #475569; border-radius: 5px; padding: 8px; white-space: nowrap; z-index: 10; font-size: 0.75rem; }}
  .heatmap-cell:hover .tooltip {{ display: block; }}

  /* Charts */
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }}
  .chart-box {{ background: #1e293b; border-radius: 10px; padding: 15px; }}
  .chart-box canvas {{ max-height: 300px; }}

  @media (max-width: 900px) {{
    .charts {{ grid-template-columns: 1fr; }}
    .summary {{ flex-direction: column; }}
  }}
</style>
</head>
<body>

<h1>SFO &harr; BCN Flight Search</h1>
<p class="subtitle">Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')} &middot; {stats['total_rows']} combinations &middot; {len(airlines)} airlines</p>

<h2>Summary</h2>
<div class="summary">
  {summary_cards}
</div>

<h2>Price by Outbound Date</h2>
<div class="charts">
  <div class="chart-box"><canvas id="outChart"></canvas></div>
  <div class="chart-box"><canvas id="retChart"></canvas></div>
</div>

<h2>Price Heatmap (Best Price per Date Pair)</h2>
<p class="subtitle">Outbound dates (rows) vs Return dates (columns). Green = cheapest, Red = most expensive. Gray = no data.</p>
<div class="heatmap-container" id="heatmapContainer"></div>

<h2>All Flights</h2>
<div class="filters">
  <label>Airline: <select id="filterAirline"><option value="">All</option></select></label>
  <label>Max Price: <input type="number" id="filterMaxPrice" placeholder="e.g. 8000" style="width:100px"></label>
  <label>Max Stops: <select id="filterMaxStops"><option value="">Any</option><option value="0">Nonstop</option><option value="1">0-1</option></select></label>
</div>
<div class="table-wrap">
  <table id="flightTable">
    <thead>
      <tr>
        <th data-col="airline">Airline</th>
        <th data-col="class">Class</th>
        <th data-col="outbound_date">Out Date</th>
        <th data-col="return_date">Ret Date</th>
        <th data-col="stay_days" data-type="num">Days</th>
        <th data-col="out_flight">Out Flight</th>
        <th data-col="out_duration">Out Duration</th>
        <th data-col="out_stops">Out Stops</th>
        <th data-col="out_price_num" data-type="num">Out Price</th>
        <th data-col="ret_flight">Ret Flight</th>
        <th data-col="ret_duration">Ret Duration</th>
        <th data-col="ret_stops">Ret Stops</th>
        <th data-col="ret_price_num" data-type="num">Ret Price</th>
        <th data-col="total_price_num" data-type="num">Total</th>
      </tr>
    </thead>
    <tbody id="tableBody"></tbody>
  </table>
</div>

<script>
const DATA = {json.dumps(table_data)};
const HEATMAP = {json.dumps(heatmap_json)};
const OUT_DATES = {json.dumps(stats['outbound_dates'])};
const RET_DATES = {json.dumps(stats['return_dates'])};
const MIN_PRICE = {stats['min_price']};
const MAX_PRICE = {stats['max_price']};
const AIRLINES = {json.dumps(airlines)};

// --- Sortable Table ---
let sortCol = 'total_price_num';
let sortAsc = true;
let filtered = [...DATA];

function renderTable() {{
  const tbody = document.getElementById('tableBody');
  const maxPrice = parseFloat(document.getElementById('filterMaxPrice').value) || Infinity;
  const airlineFilter = document.getElementById('filterAirline').value;
  const maxStops = document.getElementById('filterMaxStops').value;

  filtered = DATA.filter(r => {{
    if (r.total_price_num > maxPrice) return false;
    if (airlineFilter && r.airline !== airlineFilter) return false;
    if (maxStops !== '') {{
      const ms = parseInt(maxStops);
      const outS = parseInt(r.out_stops) || 0;
      const retS = parseInt(r.ret_stops) || 0;
      if (outS > ms || retS > ms) return false;
    }}
    return true;
  }});

  filtered.sort((a, b) => {{
    const av = a[sortCol], bv = b[sortCol];
    if (typeof av === 'number') return sortAsc ? av - bv : bv - av;
    return sortAsc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
  }});

  // Mark top 20 as deals
  const top20 = new Set(filtered.slice(0, 20));

  tbody.innerHTML = filtered.map(r => {{
    const cls = top20.has(r) ? ' class="top-deal"' : '';
    return `<tr${{cls}}>
      <td>${{r.airline}}</td><td>${{r.class}}</td>
      <td>${{r.outbound_date}}</td><td>${{r.return_date}}</td><td>${{r.stay_days}}</td>
      <td>${{r.out_flight}}</td><td>${{r.out_duration}}</td><td>${{r.out_stops}}</td>
      <td class="price-cell">${{r.out_price}}</td>
      <td>${{r.ret_flight}}</td><td>${{r.ret_duration}}</td><td>${{r.ret_stops}}</td>
      <td class="price-cell">${{r.ret_price}}</td>
      <td class="price-cell" style="color:#6ee7b7;font-size:0.9rem">${{r.total_price}}</td>
    </tr>`;
  }}).join('');

  // Update header sort indicators
  document.querySelectorAll('#flightTable th').forEach(th => {{
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.col === sortCol) {{
      th.classList.add(sortAsc ? 'sorted-asc' : 'sorted-desc');
    }}
  }});
}}

document.querySelectorAll('#flightTable th').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.col;
    if (sortCol === col) sortAsc = !sortAsc;
    else {{ sortCol = col; sortAsc = true; }}
    renderTable();
  }});
}});

// Populate airline filter
const airlineSel = document.getElementById('filterAirline');
AIRLINES.forEach(a => {{
  const opt = document.createElement('option');
  opt.value = a; opt.textContent = a;
  airlineSel.appendChild(opt);
}});

document.getElementById('filterAirline').addEventListener('change', renderTable);
document.getElementById('filterMaxPrice').addEventListener('input', renderTable);
document.getElementById('filterMaxStops').addEventListener('change', renderTable);

renderTable();

// --- Heatmap ---
function priceColor(price) {{
  if (!price || price >= Infinity) return '#1e293b';
  const ratio = (price - MIN_PRICE) / (MAX_PRICE - MIN_PRICE || 1);
  const clamped = Math.max(0, Math.min(1, ratio));
  // Green (low) -> Yellow (mid) -> Red (high)
  const r = clamped < 0.5 ? Math.round(clamped * 2 * 255) : 255;
  const g = clamped < 0.5 ? 255 : Math.round((1 - (clamped - 0.5) * 2) * 255);
  return `rgb(${{r}},${{g}},60)`;
}}

function renderHeatmap() {{
  const container = document.getElementById('heatmapContainer');
  const cols = RET_DATES.length + 1;
  let html = `<div class="heatmap" style="grid-template-columns: 85px repeat(${{RET_DATES.length}}, 55px)">`;

  // Header row
  html += '<div class="heatmap-header"></div>';
  RET_DATES.forEach(d => {{
    html += `<div class="heatmap-header">${{d.slice(5)}}</div>`;
  }});

  // Data rows
  OUT_DATES.forEach(outD => {{
    html += `<div class="heatmap-label">${{outD.slice(5)}}</div>`;
    RET_DATES.forEach(retD => {{
      const key = `${{outD}}|${{retD}}`;
      const cell = HEATMAP[key];
      if (cell) {{
        const color = priceColor(cell.price);
        const textColor = cell.price < (MIN_PRICE + MAX_PRICE) / 2 ? '#000' : '#fff';
        html += `<div class="heatmap-cell" style="background:${{color}};color:${{textColor}}">
          $${{Math.round(cell.price/1000)}}k
          <div class="tooltip">$${{cell.price.toLocaleString()}} (${{cell.airline}})<br>${{outD}} &rarr; ${{retD}}</div>
        </div>`;
      }} else {{
        html += '<div class="heatmap-cell heatmap-empty">&mdash;</div>';
      }}
    }});
  }});

  html += '</div>';
  container.innerHTML = html;
}}

renderHeatmap();

// --- Charts ---
const outChartData = {json.dumps(out_chart)};
const retChartData = {json.dumps(ret_chart)};

const chartOpts = {{
  responsive: true,
  plugins: {{
    legend: {{ labels: {{ color: '#94a3b8' }} }},
    tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': $' + (ctx.parsed.y || 0).toLocaleString() }} }}
  }},
  scales: {{
    x: {{ ticks: {{ color: '#64748b', maxRotation: 45 }} }},
    y: {{ ticks: {{ color: '#64748b', callback: v => '$' + (v/1000).toFixed(0) + 'k' }} }}
  }}
}};

new Chart(document.getElementById('outChart'), {{
  type: 'line',
  data: outChartData,
  options: {{ ...chartOpts, plugins: {{ ...chartOpts.plugins, title: {{ display: true, text: 'Best Total Price by Outbound Date', color: '#e2e8f0' }} }} }}
}});

new Chart(document.getElementById('retChart'), {{
  type: 'line',
  data: retChartData,
  options: {{ ...chartOpts, plugins: {{ ...chartOpts.plugins, title: {{ display: true, text: 'Best Total Price by Return Date', color: '#e2e8f0' }} }} }}
}});
</script>

</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML report written: {output_path}")
    return output_path


def generate_report(csv_path=None, output_path=None):
    """Main entry point (importable)."""
    csv_path = csv_path or DEFAULT_CSV
    output_path = output_path or DEFAULT_OUTPUT

    rows = load_csv(csv_path)
    if not rows:
        print("No data found in CSV!", file=sys.stderr)
        return None

    stats = compute_stats(rows)
    return generate_html(rows, stats, output_path)


def main():
    p = argparse.ArgumentParser(description="Generate flight search HTML report")
    p.add_argument("--csv", default=DEFAULT_CSV, help="Input CSV path")
    p.add_argument("--output", default=DEFAULT_OUTPUT, help="Output HTML path")
    args = p.parse_args()

    result = generate_report(args.csv, args.output)
    if result:
        print(f"\nOpen in browser: file:///{result.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
