#!/usr/bin/env python3
"""
Price tracker — wraps gf_roundtrip.py to track prices over time.
Saves each run's results with timestamps and compares to previous runs.

Used by the OpenClaw cron job to monitor price changes every 12 hours.

Usage:
    python track_prices.py --config tracker.json       # Run using saved config
    python track_prices.py --stop                       # Mark as purchased, disable tracking
    python track_prices.py --history                    # Show price history
    python track_prices.py --compare                    # Compare last two runs
"""
import sys, os, json, csv, argparse, shutil
from datetime import datetime
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS_DIR = Path(__file__).parent
VAULT_FLIGHTS = Path(os.path.expanduser("~/clawd/obsidian-vault/flights"))
TRACKER_DIR = SCRIPTS_DIR / "tracker_data"


def parse_args():
    p = argparse.ArgumentParser(description="Flight price tracker")
    p.add_argument("--config", default=str(TRACKER_DIR / "active_trackers.json"),
                   help="Path to tracker config")
    p.add_argument("--tracker-id", default=None, help="Specific tracker ID to run")
    p.add_argument("--stop", action="store_true", help="Mark flight as purchased, stop tracking")
    p.add_argument("--history", action="store_true", help="Show price history")
    p.add_argument("--compare", action="store_true", help="Compare last two runs")
    return p.parse_args()


def load_trackers(config_path):
    """Load active tracker configurations."""
    p = Path(config_path)
    if p.exists():
        return json.loads(p.read_text())
    return {"trackers": []}


def save_trackers(data, config_path):
    Path(config_path).write_text(json.dumps(data, indent=2))


def create_tracker(origin, dest, out_start, out_end, ret_start, ret_end,
                   cabin, airlines, min_stay, max_stay, date_step=2):
    """Create a new tracker config entry. Called by the skill when user initiates a search."""
    tracker_id = f"{origin.lower()}-{dest.lower()}-{datetime.now().strftime('%Y%m%d%H%M')}"
    return {
        "id": tracker_id,
        "origin": origin,
        "dest": dest,
        "out_start": out_start,
        "out_end": out_end,
        "ret_start": ret_start,
        "ret_end": ret_end,
        "cabin": cabin,
        "airlines": airlines,
        "min_stay": min_stay,
        "max_stay": max_stay,
        "date_step": date_step,
        "created": datetime.now().isoformat(),
        "active": True,
        "runs": [],
    }


def run_search(tracker):
    """Execute a search for a tracker and return results."""
    import subprocess

    python = sys.executable
    script = str(SCRIPTS_DIR / "gf_roundtrip.py")

    slug = f"{tracker['origin'].lower()}-{tracker['dest'].lower()}"
    run_id = datetime.now().strftime("%Y%m%d_%H%M")
    run_csv = str(TRACKER_DIR / f"{tracker['id']}" / f"run_{run_id}.csv")
    run_json = str(TRACKER_DIR / f"{tracker['id']}" / f"run_{run_id}.json")

    os.makedirs(os.path.dirname(run_csv), exist_ok=True)

    cmd = [
        python, script,
        "--origin", tracker["origin"],
        "--dest", tracker["dest"],
        "--cabin", tracker["cabin"],
        "--csv", run_csv,
        "--json-out", run_json,
        "--date-step", str(tracker.get("date_step", 3)),
    ]

    if tracker.get("airlines"):
        cmd += ["--airlines", tracker["airlines"]]
    if tracker.get("min_stay"):
        cmd += ["--min-stay", str(tracker["min_stay"])]
    if tracker.get("max_stay"):
        cmd += ["--max-stay", str(tracker["max_stay"])]
    if tracker.get("out_start") and tracker.get("out_end"):
        cmd += ["--out-start", tracker["out_start"], "--out-end", tracker["out_end"]]
    if tracker.get("ret_start") and tracker.get("ret_end"):
        cmd += ["--ret-start", tracker["ret_start"], "--ret-end", tracker["ret_end"]]

    print(f"Running search: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

    if result.returncode != 0:
        print(f"Search failed: {result.stderr[-500:]}", file=sys.stderr)
        return None, run_id

    print(result.stdout[-1000:])
    return run_csv, run_id


def load_run_results(csv_path):
    """Load results from a run CSV."""
    rows = []
    if not os.path.exists(csv_path):
        return rows
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                row["total_price_num"] = float(
                    row.get("total_price", "$0").replace("$", "").replace(",", "")
                )
            except:
                row["total_price_num"] = float("inf")
            rows.append(row)
    return rows


def compare_runs(prev_csv, curr_csv):
    """Compare two runs and generate a diff summary."""
    prev = load_run_results(prev_csv)
    curr = load_run_results(curr_csv)

    if not prev or not curr:
        return None

    # Best price per (airline, outbound, return) in each run
    def best_by_combo(rows):
        best = {}
        for r in rows:
            key = (r.get("airline", ""), r.get("outbound_date", ""), r.get("return_date", ""))
            price = r["total_price_num"]
            if key not in best or price < best[key]:
                best[key] = price
        return best

    prev_best = best_by_combo(prev)
    curr_best = best_by_combo(curr)

    # Overall cheapest
    prev_cheapest = min(prev, key=lambda r: r["total_price_num"])
    curr_cheapest = min(curr, key=lambda r: r["total_price_num"])

    prev_min = prev_cheapest["total_price_num"]
    curr_min = curr_cheapest["total_price_num"]
    diff = curr_min - prev_min

    # Track changes per combo
    changes = []
    all_keys = set(prev_best.keys()) | set(curr_best.keys())
    for key in all_keys:
        airline, out_d, ret_d = key
        p_price = prev_best.get(key)
        c_price = curr_best.get(key)
        if p_price and c_price:
            delta = c_price - p_price
            if abs(delta) >= 1:
                changes.append({
                    "airline": airline,
                    "outbound": out_d,
                    "return": ret_d,
                    "prev_price": p_price,
                    "curr_price": c_price,
                    "delta": delta,
                    "pct": (delta / p_price) * 100 if p_price else 0,
                })
        elif c_price and not p_price:
            changes.append({
                "airline": airline, "outbound": out_d, "return": ret_d,
                "prev_price": None, "curr_price": c_price, "delta": 0, "pct": 0,
            })

    changes.sort(key=lambda x: x["delta"])

    return {
        "prev_cheapest": prev_cheapest,
        "curr_cheapest": curr_cheapest,
        "overall_diff": diff,
        "overall_pct": (diff / prev_min * 100) if prev_min else 0,
        "changes": changes,
        "prices_dropped": len([c for c in changes if c["delta"] < 0]),
        "prices_rose": len([c for c in changes if c["delta"] > 0]),
        "prices_unchanged": len([c for c in changes if c["delta"] == 0]),
    }


def format_comparison(comp, tracker):
    """Format comparison as human-readable text for Telegram/console."""
    if not comp:
        return "Not enough data to compare (need at least 2 runs)."

    lines = []
    diff = comp["overall_diff"]
    arrow = "📉 DOWN" if diff < 0 else "📈 UP" if diff > 0 else "➡️ SAME"
    route = f"{tracker['origin']}↔{tracker['dest']}"

    lines.append(f"✈️ Flight Price Update: {route} ({tracker['cabin']})")
    lines.append(f"")
    lines.append(f"Best price: ${comp['curr_cheapest']['total_price_num']:,.0f} {arrow} (was ${comp['prev_cheapest']['total_price_num']:,.0f}, {comp['overall_pct']:+.1f}%)")
    lines.append(f"  {comp['curr_cheapest']['airline']}: {comp['curr_cheapest']['outbound_date']} → {comp['curr_cheapest']['return_date']}")
    lines.append(f"")
    lines.append(f"Changes: {comp['prices_dropped']} dropped, {comp['prices_rose']} rose, {comp['prices_unchanged']} same")

    # Show top 5 biggest drops
    drops = [c for c in comp["changes"] if c["delta"] < 0]
    if drops:
        lines.append(f"\nBiggest drops:")
        for c in drops[:5]:
            lines.append(f"  {c['airline']}: ${c['curr_price']:,.0f} (was ${c['prev_price']:,.0f}, {c['pct']:+.1f}%) {c['outbound']}→{c['return']}")

    # Show top 3 biggest rises
    rises = [c for c in comp["changes"] if c["delta"] > 0]
    if rises:
        lines.append(f"\nBiggest rises:")
        for c in rises[-3:]:
            lines.append(f"  {c['airline']}: ${c['curr_price']:,.0f} (was ${c['prev_price']:,.0f}, {c['pct']:+.1f}%) {c['outbound']}→{c['return']}")

    return "\n".join(lines)


def main():
    args = parse_args()
    TRACKER_DIR.mkdir(exist_ok=True)

    data = load_trackers(args.config)

    if args.stop:
        # Mark all (or specific) trackers as inactive
        for t in data.get("trackers", []):
            if args.tracker_id and t["id"] != args.tracker_id:
                continue
            t["active"] = False
            t["purchased_at"] = datetime.now().isoformat()
            print(f"Stopped tracker: {t['id']} ({t['origin']}→{t['dest']})")
        save_trackers(data, args.config)
        return

    if args.history:
        for t in data.get("trackers", []):
            if args.tracker_id and t["id"] != args.tracker_id:
                continue
            print(f"\n=== {t['id']} ({t['origin']}↔{t['dest']} {t['cabin']}) ===")
            print(f"Active: {t['active']}")
            for run in t.get("runs", []):
                print(f"  {run['timestamp']}: best ${run.get('best_price', '?'):,} ({run.get('best_airline', '?')})")
        return

    if args.compare:
        for t in data.get("trackers", []):
            if args.tracker_id and t["id"] != args.tracker_id:
                continue
            runs = t.get("runs", [])
            if len(runs) < 2:
                print(f"Tracker {t['id']}: need at least 2 runs to compare")
                continue
            comp = compare_runs(runs[-2]["csv_path"], runs[-1]["csv_path"])
            print(format_comparison(comp, t))
        return

    # Run all active trackers
    active = [t for t in data.get("trackers", []) if t.get("active", True)]
    if not active:
        print("No active trackers. Create one via the flight-search skill first.")
        return

    for tracker in active:
        print(f"\n{'='*60}")
        print(f"Tracker: {tracker['id']}")
        print(f"Route: {tracker['origin']}↔{tracker['dest']} | {tracker['cabin']}")
        print(f"{'='*60}")

        csv_path, run_id = run_search(tracker)
        if not csv_path:
            print("Search failed, skipping comparison")
            continue

        # Load results to get summary
        results = load_run_results(csv_path)
        best = min(results, key=lambda r: r["total_price_num"]) if results else None

        run_info = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "csv_path": csv_path,
            "total_results": len(results),
            "best_price": best["total_price_num"] if best else None,
            "best_airline": best.get("airline", "") if best else None,
            "best_dates": f"{best['outbound_date']}→{best['return_date']}" if best else None,
        }
        tracker.setdefault("runs", []).append(run_info)

        # Compare with previous run
        if len(tracker["runs"]) >= 2:
            prev_run = tracker["runs"][-2]
            comp = compare_runs(prev_run["csv_path"], csv_path)
            report = format_comparison(comp, tracker)
            print(f"\n{report}")
        elif best:
            print(f"\nFirst run — Best: {best['airline']} ${best['total_price_num']:,.0f} "
                  f"({best['outbound_date']}→{best['return_date']})")

        # Copy latest CSV to vault for easy access
        slug = f"{tracker['origin'].lower()}-{tracker['dest'].lower()}"
        vault_csv = VAULT_FLIGHTS / f"{slug}-roundtrip.csv"
        vault_html = VAULT_FLIGHTS / f"{slug}-report.html"
        shutil.copy2(csv_path, vault_csv)

        # Generate fresh report
        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from generate_report import generate_report
            generate_report(str(vault_csv), str(vault_html))
        except Exception as e:
            print(f"Report: {e}")

    save_trackers(data, args.config)
    print("\nDone. Tracker state saved.")


if __name__ == "__main__":
    main()
