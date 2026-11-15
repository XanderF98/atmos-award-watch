"""Small client for the seats.aero Partner API (cached award availability).

Only the read endpoints this project needs:
  GET /search      availability summaries, one per route and day
  GET /trips/{id}  the individual flights behind one summary
  GET /routes      which airport pairs are tracked for a program

Docs: https://developers.seats.aero/reference
Uses the standard library only, so the scheduled job needs no installs.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class SeatsAeroError(RuntimeError):
    """A request to seats.aero failed, with a message a person can act on."""


_HINTS = {
    401: "the API key was rejected. Check SEATS_AERO_API_KEY.",
    403: "the API key is not allowed to do this. API access needs a Pro subscription.",
    404: "nothing found for that request.",
    429: "the daily call quota is used up. It resets within a day.",
}


def _base_url() -> str:
    return os.environ.get("SEATS_AERO_BASE_URL", "https://seats.aero/partnerapi").rstrip("/")


def _get(url: str):
    key = os.environ.get("SEATS_AERO_API_KEY", "").strip()
    if not key:
        raise SeatsAeroError(
            "SEATS_AERO_API_KEY is not set. Create a key at https://seats.aero/apikey "
            "(Pro subscription) and set it as an environment variable or repository secret."
        )
    request = urllib.request.Request(
        url,
        headers={
            "Partner-Authorization": key,
            "Accept": "application/json",
            "User-Agent": "atmos-award-watch",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        hint = _HINTS.get(error.code, "unexpected response.")
        raise SeatsAeroError(f"seats.aero returned HTTP {error.code}: {hint}") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise SeatsAeroError(f"Could not reach seats.aero: {error}") from None
    except json.JSONDecodeError:
        raise SeatsAeroError("seats.aero returned a response that was not JSON.") from None


def search(
    origins: list[str],
    destinations: list[str],
    start_date: str,
    end_date: str,
    *,
    program: str = "alaska",
    cabins: list[str] | None = None,
    nonstop_only: bool = False,
    max_pages: int = 5,
) -> list[dict]:
    """Cached availability for every origin/destination pair between two dates.

    Returns raw availability objects for one mileage program. One call covers
    all the airport pairs, so a watch normally costs a single API call.
    """
    params = {
        "origin_airport": ",".join(origins),
        "destination_airport": ",".join(destinations),
        "start_date": start_date,
        "end_date": end_date,
        "sources": program,
        "take": 1000,
        "order_by": "lowest_mileage",
    }
    if cabins:
        params["cabins"] = ",".join(cabins)
    if nonstop_only:
        params["only_direct_flights"] = "true"

    base = _base_url()
    url = f"{base}/search?{urllib.parse.urlencode(params)}"
    found: dict[str, dict] = {}
    for _ in range(max_pages):
        page = _get(url)
        rows = page.get("data") or []
        for row in rows:
            found.setdefault(row.get("ID"), row)  # pages can overlap, so key by ID
        if not rows or not page.get("hasMore"):
            break
        if page.get("moreURL"):
            parts = urllib.parse.urlsplit(base)
            url = f"{parts.scheme}://{parts.netloc}{page['moreURL']}"
        else:
            more = {**params, "skip": len(found)}
            if page.get("cursor") is not None:
                more["cursor"] = page["cursor"]
            url = f"{base}/search?{urllib.parse.urlencode(more)}"

    return only_program(list(found.values()), program)


def only_program(rows: list[dict], program: str) -> list[dict]:
    """Keep rows from one mileage program.

    The request already filters by program. Filtering again here means a change
    in the API's filter name can't let other programs' prices leak in.
    """
    def source(row: dict) -> str:
        return (row.get("Source") or (row.get("Route") or {}).get("Source") or program).lower()

    return [row for row in rows if source(row) == program.lower()]


def trips(availability_id: str) -> dict:
    """The individual flights (with times, flight numbers, taxes) behind one availability ID."""
    safe_id = urllib.parse.quote(str(availability_id), safe="")
    return _get(f"{_base_url()}/trips/{safe_id}")


def routes(program: str = "alaska") -> set[str]:
    """Airport pairs seats.aero tracks for a program, as 'SEA-FCO' strings.

    Some accounts are not allowed to call this; callers should handle SeatsAeroError.
    """
    response = _get(f"{_base_url()}/routes?{urllib.parse.urlencode({'source': program})}")
    rows = response.get("data", []) if isinstance(response, dict) else response
    return {f"{r.get('OriginAirport')}-{r.get('DestinationAirport')}" for r in rows}
