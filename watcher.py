"""Daily award check. Run on a schedule by GitHub Actions, or by hand.

For every watch in watchlist.json this:
  1. asks seats.aero for cached award space (one API call per watch),
  2. applies the deal rules in deals.py,
  3. pairs ways out with ways back and prices the whole trip (trip.py),
  4. saves a snapshot, price history, a dashboard page and a chart,
  5. writes an alert file when a deal is new or its price dropped.

Usage:
  python watcher.py                 real run, needs SEATS_AERO_API_KEY
  python watcher.py --check-routes  first thing to run with a new key: is each route covered?
  python watcher.py --demo          sample data, no key; prints the dashboard
"""

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import deals
import report
import seats_aero
import trip

ROOT = Path(__file__).parent
HISTORY_FIELDS = [
    "run_date", "watch", "cabin", "cheapest_miles", "cheapest_date",
    "cheapest_route", "days_available", "deals",
]
TRIP_FIELDS = ["run_date", "option", "total_points", "out_date", "back_date", "nights"]
MAX_DETAIL_LOOKUPS = 5  # extra API calls spent describing new deals, per run


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    for watch in config["watches"]:
        for field in ("name", "origins", "destinations", "start_date", "end_date"):
            if field not in watch:
                raise SystemExit(f"{path.name}: a watch is missing '{field}': {watch}")
    return config


def trip_watches(config: dict) -> tuple[str, str] | None:
    """Names of the outbound and return watches to pair, if the config has both."""
    settings = config.get("trip") or {}
    names = [w["name"] for w in config["watches"]]
    out = settings.get("outbound") or (names[0] if len(names) > 1 else None)
    back = settings.get("return") or (names[1] if len(names) > 1 else None)
    return (out, back) if out in names and back in names else None


def check(config: dict, search=seats_aero.search, today: date | None = None) -> dict:
    """Fetch and evaluate every watch. Returns the snapshot saved as latest.json."""
    program = config.get("program", "alaska")
    now = datetime.now(timezone.utc)
    today = today or now.date()
    window = config.get("release_window_days", trip.RELEASE_WINDOW_DAYS)
    snapshot = {
        "generated_at": now.isoformat(timespec="seconds"),
        "program": program,
        "passengers": config.get("passengers", 1),
        "watches": [],
        "trips": [],
    }
    options_by_watch = {}
    for watch in config["watches"]:
        rows = search(
            watch["origins"], watch["destinations"], watch["start_date"], watch["end_date"],
            program=program,
        )
        options = deals.options_for_watch(rows, watch)
        options_by_watch[watch["name"]] = deals.prefer_main_airports(options, watch, config)
        snapshot["watches"].append(
            {
                "name": watch["name"],
                "start_date": watch["start_date"],
                "end_date": watch["end_date"],
                "options_found": len(options),
                "release": trip.release_calendar(watch, today, window),
                "coverage": trip.route_coverage(rows, watch),
                "cabins": deals.cabin_summary(options),
                "deals": deals.find_deals(options, watch, config),
            }
        )
    pair = trip_watches(config)
    if pair:
        snapshot["trips"] = trip.pair_trips(options_by_watch[pair[0]], options_by_watch[pair[1]], config)
    return snapshot


def _rewrite_csv(path: Path, fields: list[str], run_date: str, new_rows: list[dict]) -> list[dict]:
    """Replace any rows from an earlier run today, append the new ones, return all rows."""
    rows = []
    if path.exists():
        with path.open(newline="") as handle:
            rows = [r for r in csv.DictReader(handle) if r["run_date"] != run_date]
    rows += new_rows
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def update_history(data_dir: Path, snapshot: dict) -> list[dict]:
    """Add today's rows to both history files. Returns the full trip history."""
    run_date = snapshot["generated_at"][:10]
    cabin_rows = [
        {
            "run_date": run_date,
            "watch": watch["name"],
            "cabin": cabin,
            **summary,
            "deals": sum(1 for d in watch["deals"] if d["cabin"] == cabin),
        }
        for watch in snapshot["watches"]
        for cabin, summary in watch["cabins"].items()
    ]
    _rewrite_csv(data_dir / "history.csv", HISTORY_FIELDS, run_date, cabin_rows)
    trip_rows = [
        {
            "run_date": run_date,
            "option": t["label"],
            "total_points": t["total_points"],
            "out_date": t["out"]["date"],
            "back_date": t["back"]["date"],
            "nights": t["nights"],
        }
        for t in snapshot["trips"]
    ]
    return _rewrite_csv(data_dir / "trips.csv", TRIP_FIELDS, run_date, trip_rows)


def chart_series(trip_history: list[dict], keep: int = 4) -> dict[str, list[tuple[str, int]]]:
    """Trip history as chart lines: the options that are cheapest in the latest run."""
    if not trip_history:
        return {}
    latest = max(r["run_date"] for r in trip_history)
    current = sorted(
        (r for r in trip_history if r["run_date"] == latest), key=lambda r: int(r["total_points"])
    )
    series = {}
    for row in current[:keep]:
        series[row["option"]] = [
            (r["run_date"], int(r["total_points"])) for r in trip_history if r["option"] == row["option"]
        ]
    return series


def write_dashboard(data_dir: Path, snapshot: dict, trip_history: list[dict], config: dict) -> None:
    (data_dir / "chart.svg").write_text(
        report.chart_svg(chart_series(trip_history), config.get("points_balance")) + "\n"
    )
    (data_dir / "README.md").write_text(report.dashboard_markdown(snapshot) + "\n")


def lookup_details(new_deals: list[dict], passengers: int) -> dict[str, dict]:
    """Flight numbers and times for the first few new deals. Failures are not fatal."""
    details = {}
    for deal in new_deals[:MAX_DETAIL_LOOKUPS]:
        try:
            found = deals.describe_trip(seats_aero.trips(deal["id"]), deal["cabin"], passengers)
        except seats_aero.SeatsAeroError as error:
            print(f"Could not load flight details: {error}", file=sys.stderr)
            break
        if found:
            details[deals.deal_key(deal)] = found
    return details


def check_routes(config: dict) -> int:
    """Report whether the data source covers each airport pair in the watchlist."""
    program = config.get("program", "alaska")
    tracked = None
    try:
        tracked = seats_aero.routes(program)
        print(f"seats.aero tracks {len(tracked)} routes for '{program}'.\n")
    except seats_aero.SeatsAeroError as error:
        print(f"Could not load the tracked-route list ({error})")
        print("Falling back to checking which routes return any data.\n")

    missing = 0
    for watch in config["watches"]:
        rows = seats_aero.search(
            watch["origins"], watch["destinations"], watch["start_date"], watch["end_date"],
            program=program,
        )
        print(watch["name"])
        for pair, days in trip.route_coverage(rows, watch).items():
            if tracked is not None:
                status = "tracked" if pair in tracked else "NOT tracked"
                missing += pair not in tracked
            else:
                status = "returning data" if days else "no data returned"
            print(f"  {pair}: {status} ({days} days of data in your date range)")
        print()
    if missing:
        print(
            f"{missing} route(s) are not tracked, so they will never alert. seats.aero mostly "
            "tracks airport pairs with a nonstop flight. Pro members can request a route on its "
            "Routes page, or you can swap in a nearby airport that is tracked."
        )
    return 0


def set_output(name: str, value: str) -> None:
    """Pass a value to later GitHub Actions steps (does nothing outside Actions)."""
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=ROOT / "watchlist.json", type=Path)
    parser.add_argument("--data-dir", default=ROOT / "data", type=Path)
    parser.add_argument("--alert-file", default=ROOT / "alert.md", type=Path)
    parser.add_argument("--demo", action="store_true", help="use sample data; prints the dashboard")
    parser.add_argument("--save-demo", action="store_true", help="with --demo, also write files to --data-dir")
    parser.add_argument("--check-routes", action="store_true", help="report route coverage and exit")
    parser.add_argument("--today", type=date.fromisoformat, help="pretend today is this date (YYYY-MM-DD)")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.demo:
        sample = json.loads((ROOT / "tests" / "fixtures" / "search_response.json").read_text())
        program = config.get("program", "alaska")
        snapshot = check(
            config,
            search=lambda *a, **k: seats_aero.only_program(sample["data"], program),
            today=args.today,
        )
        if args.save_demo:
            args.data_dir.mkdir(parents=True, exist_ok=True)
            history = update_history(args.data_dir, snapshot)
            write_dashboard(args.data_dir, snapshot, history, config)
            (args.data_dir / "latest.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        print(report.dashboard_markdown(snapshot, chart_file=None))
        return 0

    try:
        if args.check_routes:
            return check_routes(config)
        snapshot = check(config, today=args.today)
    except seats_aero.SeatsAeroError as error:
        print(f"Award check failed: {error}", file=sys.stderr)
        return 1

    args.data_dir.mkdir(parents=True, exist_ok=True)
    alerted_path = args.data_dir / "alerted.json"
    alerted = json.loads(alerted_path.read_text()) if alerted_path.exists() else {}

    new_by_watch, still_alerted, all_new = {}, {}, []
    for watch in snapshot["watches"]:
        new, record = deals.split_new(watch["deals"], alerted.get(watch["name"], {}))
        new_by_watch[watch["name"]] = new
        still_alerted[watch["name"]] = record
        all_new += new

    (args.data_dir / "latest.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    alerted_path.write_text(json.dumps(still_alerted, indent=2, sort_keys=True) + "\n")
    history = update_history(args.data_dir, snapshot)
    write_dashboard(args.data_dir, snapshot, history, config)

    dashboard = report.dashboard_markdown(snapshot, chart_file=None)
    print(dashboard)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(dashboard + "\n")

    if all_new:
        details = lookup_details(all_new, config.get("passengers", 1))
        body = deals.alert_markdown(new_by_watch, config, details)
        whole_trip = "\n".join(["## The whole trip right now", "", *report.trips_table(snapshot["trips"]), ""])
        args.alert_file.write_text(f"{whole_trip}\n{body}\n")
        best = deals.headline(all_new, config.get("max_miles", {}))
        title = (
            f"{len(all_new)} new award deal(s): {best['cabin']} {best['origin']}-{best['destination']} "
            f"for {best['miles']:,} points ({snapshot['generated_at'][:10]})"
        )
        print(f"\n{title}\nAlert written to {args.alert_file}")
        set_output("title", title)
    set_output("new_deals", str(len(all_new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
