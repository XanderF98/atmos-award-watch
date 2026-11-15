"""Daily award check. Run by GitHub Actions on a schedule, or by hand.

For every watch in watchlist.json this:
  1. asks seats.aero for cached award space (one API call per watch),
  2. applies the deal rules in deals.py,
  3. saves a snapshot and a small price history under data/,
  4. writes an alert file when a deal is new or its price dropped.

Usage:
  python watcher.py                 real run, needs SEATS_AERO_API_KEY
  python watcher.py --demo          sample data, no key, nothing saved
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import deals
import seats_aero

ROOT = Path(__file__).parent
HISTORY_FIELDS = [
    "run_date", "watch", "cabin", "cheapest_miles", "cheapest_date",
    "cheapest_route", "days_available", "deals",
]
MAX_DETAIL_LOOKUPS = 5  # extra API calls spent describing new deals, per run


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    for watch in config["watches"]:
        for field in ("name", "origins", "destinations", "start_date", "end_date"):
            if field not in watch:
                raise SystemExit(f"watchlist.json: watch is missing '{field}': {watch}")
    return config


def check(config: dict, search=seats_aero.search) -> dict:
    """Fetch and evaluate every watch. Returns the snapshot saved as data/latest.json."""
    program = config.get("program", "alaska")
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "program": program,
        "passengers": config.get("passengers", 1),
        "watches": [],
    }
    for watch in config["watches"]:
        rows = search(
            watch["origins"], watch["destinations"], watch["start_date"], watch["end_date"],
            program=program,
        )
        options = deals.options_for_watch(rows, watch)
        snapshot["watches"].append(
            {
                "name": watch["name"],
                "start_date": watch["start_date"],
                "end_date": watch["end_date"],
                "options_found": len(options),
                "cabins": deals.cabin_summary(options),
                "deals": deals.find_deals(options, watch, config),
            }
        )
    return snapshot


def update_history(path: Path, snapshot: dict) -> None:
    """Add today's rows to the history file, replacing any from an earlier run today."""
    run_date = snapshot["generated_at"][:10]
    rows = []
    if path.exists():
        with path.open(newline="") as handle:
            rows = [r for r in csv.DictReader(handle) if r["run_date"] != run_date]
    for watch in snapshot["watches"]:
        for cabin, summary in watch["cabins"].items():
            rows.append(
                {
                    "run_date": run_date,
                    "watch": watch["name"],
                    "cabin": cabin,
                    **summary,
                    "deals": sum(1 for d in watch["deals"] if d["cabin"] == cabin),
                }
            )
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def lookup_details(new_deals: list[dict], passengers: int) -> dict[str, dict]:
    """Flight numbers and times for the first few new deals. Failures are not fatal."""
    details = {}
    for deal in new_deals[:MAX_DETAIL_LOOKUPS]:
        try:
            trip = deals.describe_trip(seats_aero.trips(deal["id"]), deal["cabin"], passengers)
        except seats_aero.SeatsAeroError as error:
            print(f"Could not load flight details: {error}", file=sys.stderr)
            break
        if trip:
            details[deals.deal_key(deal)] = trip
    return details


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
    parser.add_argument("--demo", action="store_true", help="use sample data and save nothing")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.demo:
        sample = json.loads((ROOT / "tests" / "fixtures" / "search_response.json").read_text())
        program = config.get("program", "alaska")
        snapshot = check(config, search=lambda *a, **k: seats_aero.only_program(sample["data"], program))
        print(deals.summary_markdown(snapshot))
        new_by_watch = {w["name"]: w["deals"] for w in snapshot["watches"]}
        print(deals.alert_markdown(new_by_watch, config, {}))
        return 0

    try:
        snapshot = check(config)
    except seats_aero.SeatsAeroError as error:
        print(f"Award check failed: {error}", file=sys.stderr)
        return 1

    args.data_dir.mkdir(exist_ok=True)
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
    update_history(args.data_dir / "history.csv", snapshot)

    summary = deals.summary_markdown(snapshot)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(summary + "\n")

    if all_new:
        details = lookup_details(all_new, config.get("passengers", 1))
        args.alert_file.write_text(deals.alert_markdown(new_by_watch, config, details) + "\n")
        best = deals.sort_options(all_new)[0]
        title = (
            f"{len(all_new)} new award deal(s): {best['cabin']} from {best['miles']:,} points "
            f"({snapshot['generated_at'][:10]})"
        )
        print(f"\n{title}\nAlert written to {args.alert_file}")
        set_output("title", title)
    set_output("new_deals", str(len(all_new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
