"""Atmos award watch MCP server.

Lets an AI agent (for example a Copilot Studio agent) answer questions about
award flights bookable with Alaska Atmos Rewards points: what the daily check
has found, how prices have moved, and live lookups for other routes and dates.

Run locally:   python server.py
Endpoint:      http://localhost:8000/mcp   (Streamable HTTP transport)

Requires:      pip install "mcp>=2"

Environment:
  SEATS_AERO_API_KEY     seats.aero Pro API key (needed for the two live tools)
  MCP_API_KEY            if set, callers must send it in an X-API-Key header
  DATA_BASE_URL          where to read data/ and watchlist.json from; unset = local files
  LIVE_CALL_DAILY_LIMIT  cap on seats.aero calls this server makes per day (default 50)
"""

import csv
import hmac
import io
import json
import os
import re
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import MCPServer

import deals
import seats_aero

ROOT = Path(__file__).parent
DATA_BASE_URL = os.environ.get("DATA_BASE_URL", "").rstrip("/")
LIVE_CALL_DAILY_LIMIT = int(os.environ.get("LIVE_CALL_DAILY_LIMIT", "50"))

mcp = MCPServer(
    "atmos-award-watch",
    instructions=(
        "Award flight availability for Alaska Atmos Rewards points. Points prices are per "
        "person, one way. Data comes from seats.aero's cache, so always tell the user to "
        "confirm on alaskaair.com before booking. Prefer get_current_deals and "
        "get_price_history, which are free; search_awards and get_flight_details each "
        "spend one call from a limited daily quota."
    ),
)

_cache: dict[str, tuple[float, object]] = {}
_live_calls = {"day": "", "count": 0}


def cached(key: str, ttl_seconds: int, load):
    """Return a cached value, or load and remember it."""
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl_seconds:
        return hit[1]
    value = load()
    _cache[key] = (now, value)
    return value


def read_text(relative_path: str) -> str | None:
    """Read a repo file: from DATA_BASE_URL when hosted, else from disk. None if missing."""
    def load():
        try:
            if DATA_BASE_URL:
                request = urllib.request.Request(
                    f"{DATA_BASE_URL}/{relative_path}", headers={"User-Agent": "atmos-award-watch"}
                )
                with urllib.request.urlopen(request, timeout=20) as response:
                    return response.read().decode()
            return (ROOT / relative_path).read_text()
        except (OSError, ValueError):
            return None

    return cached(f"file:{relative_path}", 600, load)


def spend_live_call() -> str | None:
    """Count one seats.aero call. Returns an error message when the daily cap is hit."""
    today = datetime.now(timezone.utc).date().isoformat()
    if _live_calls["day"] != today:
        _live_calls.update(day=today, count=0)
    if _live_calls["count"] >= LIVE_CALL_DAILY_LIMIT:
        return (
            f"This server's limit of {LIVE_CALL_DAILY_LIMIT} live lookups per day is used up. "
            "get_current_deals and get_price_history still work."
        )
    _live_calls["count"] += 1
    return None


def airports(value: str) -> list[str] | None:
    codes = [c.strip().upper() for c in value.split(",") if c.strip()]
    if 1 <= len(codes) <= 3 and all(re.fullmatch(r"[A-Z]{3}", c) for c in codes):
        return codes
    return None


@mcp.tool()
def get_watchlist() -> dict:
    """The routes and dates being watched every day, and the rules that decide what counts as a deal (points limit per cabin, number of travelers, taxes cap, backup airports)."""
    text = read_text("watchlist.json")
    return json.loads(text) if text else {"error": "watchlist.json was not found."}


@mcp.tool()
def get_current_deals(cabin: str | None = None) -> dict:
    """Award flights from the latest daily check that meet the watchlist rules, cheapest first, plus the cheapest price seen in each cabin. Optional cabin: economy, premium, business or first. Free to call; use this first for questions about the watched trip."""
    text = read_text("data/latest.json")
    if not text:
        return {"error": "No results yet. The daily check has not run."}
    snapshot = json.loads(text)
    if cabin:
        cabin = cabin.lower()
        if cabin not in deals.CABIN_PREFIX:
            return {"error": "cabin must be economy, premium, business or first."}
        for watch in snapshot["watches"]:
            watch["deals"] = [d for d in watch["deals"] if d["cabin"] == cabin]
            watch["cabins"] = {k: v for k, v in watch["cabins"].items() if k == cabin}
    for watch in snapshot["watches"]:
        watch["deals_total"] = len(watch["deals"])
        watch["deals"] = watch["deals"][:20]
    return snapshot


@mcp.tool()
def get_price_history(cabin: str | None = None, days: int = 30) -> dict:
    """How the cheapest points price for each watched route and cabin has changed over recent daily checks, with the lowest price seen so far. Use for questions like 'is this a good price?' or 'has business class gotten cheaper?'. Free to call."""
    text = read_text("data/history.csv")
    if not text:
        return {"error": "No history yet. The daily check has not run."}
    rows = list(csv.DictReader(io.StringIO(text)))
    if cabin:
        rows = [r for r in rows if r["cabin"] == cabin.lower()]
    run_dates = sorted({r["run_date"] for r in rows})[-max(1, min(days, 365)):]
    series: dict[str, dict] = {}
    for row in rows:
        if row["run_date"] not in run_dates:
            continue
        entry = series.setdefault(
            f"{row['watch']} / {row['cabin']}", {"lowest_seen": None, "checks": []}
        )
        miles = int(row["cheapest_miles"])
        entry["checks"].append(
            {
                "run_date": row["run_date"],
                "cheapest_miles": miles,
                "on": row["cheapest_date"],
                "route": row["cheapest_route"],
                "days_available": int(row["days_available"]),
            }
        )
        if entry["lowest_seen"] is None or miles < entry["lowest_seen"]:
            entry["lowest_seen"] = miles
    return {"checks_covered": len(run_dates), "series": series}


@mcp.tool()
def search_awards(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    cabin: str | None = None,
    nonstop_only: bool = False,
) -> dict:
    """Live lookup of Atmos award space for any route and date range, for questions the daily check does not cover. origin and destination are IATA airport codes, up to three each, comma separated (e.g. 'SEA,PDX'). Dates are YYYY-MM-DD and at most 60 days apart. Returns up to 40 options, cheapest first within each cabin, each with an id for get_flight_details. Spends one call from a limited daily quota."""
    origins, destinations = airports(origin), airports(destination)
    if not origins or not destinations:
        return {"error": "origin and destination must be 1 to 3 IATA codes, like 'SEA' or 'SEA,PDX'."}
    try:
        span = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days
    except ValueError:
        return {"error": "Dates must be YYYY-MM-DD."}
    if not 0 <= span <= 60:
        return {"error": "end_date must be on or after start_date and at most 60 days later."}
    if cabin and cabin.lower() not in deals.CABIN_PREFIX:
        return {"error": "cabin must be economy, premium, business or first."}

    key = f"search:{origins}:{destinations}:{start_date}:{end_date}:{nonstop_only}"
    hit = _cache.get(key)
    if not (hit and time.time() - hit[0] < 6 * 3600):
        blocked = spend_live_call()
        if blocked:
            return {"error": blocked}
    try:
        rows = cached(
            key,
            6 * 3600,
            lambda: seats_aero.search(
                origins, destinations, start_date, end_date, nonstop_only=nonstop_only
            ),
        )
    except seats_aero.SeatsAeroError as error:
        return {"error": str(error)}

    watch = {"origins": origins, "destinations": destinations, "start_date": start_date, "end_date": end_date}
    options = deals.options_for_watch(rows, watch)
    if cabin:
        options = [o for o in options if o["cabin"] == cabin.lower()]
    if nonstop_only:
        options = [o for o in options if o["nonstop"]]
    return {
        "program": "Alaska Atmos Rewards",
        "note": "Points are per person, one way. Cached data: confirm on alaskaair.com.",
        "options_found": len(options),
        "cheapest_by_cabin": deals.cabin_summary(options),
        "options": options[:40],
    }


@mcp.tool()
def get_flight_details(availability_id: str, cabin: str = "business") -> dict:
    """The actual flights behind one award option: flight numbers, stops, departure and arrival times, exact taxes, seats left and a booking link. availability_id is the 'id' from get_current_deals or search_awards. Spends one call from a limited daily quota."""
    if cabin.lower() not in deals.CABIN_PREFIX:
        return {"error": "cabin must be economy, premium, business or first."}
    key = f"trips:{availability_id}"
    hit = _cache.get(key)
    if not (hit and time.time() - hit[0] < 3600):
        blocked = spend_live_call()
        if blocked:
            return {"error": blocked}
    try:
        response = cached(key, 3600, lambda: seats_aero.trips(availability_id))
    except seats_aero.SeatsAeroError as error:
        return {"error": str(error)}
    trip = deals.describe_trip(response, cabin.lower())
    return trip or {"error": f"No {cabin} flights found for that id. The space may be gone."}


def require_api_key(app, expected: str):
    """Wrap the web app so every HTTP request must carry the shared key."""
    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            given = headers.get("x-api-key") or headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(given.encode(), expected.encode()):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": b'{"error": "Missing or wrong API key."}'})
                return
        await app(scope, receive, send)

    return guarded


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 so a hosting service can reach it; PORT is set by most hosts.
    app = mcp.streamable_http_app(stateless_http=True, host="0.0.0.0")
    api_key = os.environ.get("MCP_API_KEY", "").strip()
    if api_key:
        app = require_api_key(app, api_key)
    else:
        print("MCP_API_KEY is not set: anyone who can reach this server can call it.")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
