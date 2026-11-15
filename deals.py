"""Turn raw seats.aero availability into options, deals and alerts.

Everything here is a pure function of its inputs: no network and no files.
That keeps the rules easy to test and lets the scheduled job and the MCP
server share them.
"""

# seats.aero prefixes each cabin's fields with a letter, e.g. JMileageCost.
CABIN_PREFIX = {"economy": "Y", "premium": "W", "business": "J", "first": "F"}
CABIN_ORDER = ["first", "business", "premium", "economy"]


def _int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def flatten(row: dict) -> list[dict]:
    """One availability object -> one option per cabin that has award space."""
    route = row.get("Route") or {}
    day = (row.get("Date") or row.get("ParsedDate") or "")[:10]
    options = []
    for cabin, prefix in CABIN_PREFIX.items():
        miles = _int(row.get(f"{prefix}MileageCost"))
        if not row.get(f"{prefix}Available") or not miles:
            continue
        taxes_cents = _int(row.get(f"{prefix}TotalTaxes"))
        options.append(
            {
                "id": row.get("ID"),
                "origin": route.get("OriginAirport"),
                "destination": route.get("DestinationAirport"),
                "date": day,
                "cabin": cabin,
                "miles": miles,  # per person, one way
                "taxes": round(taxes_cents / 100, 2) if taxes_cents else None,
                "taxes_currency": row.get("TaxesCurrency") or None,
                "seats": _int(row.get(f"{prefix}RemainingSeats")) or None,  # None = unknown
                "nonstop": bool(row.get(f"{prefix}Direct")),
                "airlines": row.get(f"{prefix}Airlines") or "",
                "last_seen": row.get("UpdatedAt"),
            }
        )
    return options


def options_for_watch(rows: list[dict], watch: dict) -> list[dict]:
    """Flatten rows and keep only the airports and dates the watch asks for."""
    origins, destinations = set(watch["origins"]), set(watch["destinations"])
    options = []
    for row in rows:
        for option in flatten(row):
            if (
                option["origin"] in origins
                and option["destination"] in destinations
                and watch["start_date"] <= option["date"] <= watch["end_date"]
            ):
                options.append(option)
    return sort_options(options)


def sort_options(options: list[dict]) -> list[dict]:
    return sorted(
        options,
        key=lambda o: (CABIN_ORDER.index(o["cabin"]), o["miles"], o["date"], o["origin"]),
    )


def find_deals(options: list[dict], watch: dict, settings: dict) -> list[dict]:
    """Apply the watchlist rules. An option is a deal when:

    1. its points price is at or under the limit for its cabin,
    2. it has enough seats for everyone (when the seat count is known),
    3. its taxes are under the cap (when known and in US dollars), and
    4. if it uses a backup airport, it beats the best main-airport deal in the
       same cabin by the configured margin, or there is no such deal.
    """
    limits = settings.get("max_miles", {})
    passengers = settings.get("passengers", 1)
    max_taxes = settings.get("max_taxes_usd")

    def passes(option: dict) -> bool:
        limit = limits.get(option["cabin"])
        if limit is None or option["miles"] > limit:
            return False
        if option["seats"] is not None and option["seats"] < passengers:
            return False
        in_dollars = (option["taxes_currency"] or "USD") == "USD"
        if max_taxes is not None and option["taxes"] is not None and in_dollars:
            if option["taxes"] > max_taxes:
                return False
        return True

    good = [o for o in options if passes(o)]
    return sort_options(prefer_main_airports(good, watch, settings))


def prefer_main_airports(options: list[dict], watch: dict, settings: dict) -> list[dict]:
    """Drop backup-airport options that don't earn the extra travel.

    A backup-airport option stays only if no main-airport option exists in the
    same cabin, or it is cheaper than the best one by the configured margin.
    Kept backup options are marked with backup_airport=True.
    """
    margin = settings.get("backup_airport_min_savings", 0)
    backups = set(watch.get("backup_airports") or [])

    def is_backup(option: dict) -> bool:
        return option["origin"] in backups or option["destination"] in backups

    best_main: dict[str, int] = {}
    for option in options:
        if not is_backup(option):
            cabin = option["cabin"]
            best_main[cabin] = min(option["miles"], best_main.get(cabin, option["miles"]))

    kept = []
    for option in options:
        if is_backup(option):
            main = best_main.get(option["cabin"])
            if main is not None and main - option["miles"] < margin:
                continue  # not enough cheaper to be worth leaving the main airport
            option = {**option, "backup_airport": True}
        kept.append(option)
    return kept


def cabin_summary(options: list[dict]) -> dict[str, dict]:
    """Per cabin: the cheapest option and how many days have any space."""
    summary = {}
    for cabin in CABIN_ORDER:
        in_cabin = [o for o in options if o["cabin"] == cabin]
        if not in_cabin:
            continue
        cheapest = min(in_cabin, key=lambda o: (o["miles"], o["date"]))
        summary[cabin] = {
            "cheapest_miles": cheapest["miles"],
            "cheapest_date": cheapest["date"],
            "cheapest_route": f"{cheapest['origin']}-{cheapest['destination']}",
            "days_available": len({o["date"] for o in in_cabin}),
        }
    return summary


def headline(deals: list[dict], limits: dict[str, int]) -> dict:
    """The deal to lead an alert with: the one furthest under its cabin's points limit.

    On a tie the nicer cabin wins, so business at its limit leads economy at its limit.
    """
    return min(
        deals,
        key=lambda d: (d["miles"] / limits.get(d["cabin"], d["miles"]), CABIN_ORDER.index(d["cabin"])),
    )


def deal_key(option: dict) -> str:
    return f"{option['origin']}-{option['destination']}|{option['date']}|{option['cabin']}"


def split_new(deals: list[dict], already_alerted: dict[str, int]) -> tuple[list[dict], dict[str, int]]:
    """Which deals are worth a new alert, and the record to keep for next time.

    A deal alerts when it has not been alerted before or its price dropped.
    The record holds only deals that still exist, so one that disappears and
    later comes back alerts again.
    """
    new = [
        d for d in deals
        if deal_key(d) not in already_alerted or d["miles"] < already_alerted[deal_key(d)]
    ]
    return new, {deal_key(d): d["miles"] for d in deals}


def describe_trip(trips_response: dict, cabin: str, passengers: int = 1) -> dict | None:
    """Pick the cheapest actual flight for a cabin out of a /trips response."""
    trips = [
        t for t in (trips_response.get("data") or [])
        if (t.get("Cabin") or "").lower() == cabin
        and (not _int(t.get("RemainingSeats")) or _int(t.get("RemainingSeats")) >= passengers)
    ]
    if not trips:
        return None
    trip = min(trips, key=lambda t: (_int(t.get("MileageCost")) or 0, _int(t.get("TotalDuration")) or 0))
    links = trips_response.get("booking_links") or []
    primary = next((l for l in links if l.get("primary")), links[0] if links else {})
    taxes_cents = _int(trip.get("TotalTaxes"))
    return {
        "flights": trip.get("FlightNumbers") or "",
        "stops": _int(trip.get("Stops")) or 0,
        "departs": trip.get("DepartsAt"),
        "arrives": trip.get("ArrivesAt"),
        "duration_minutes": _int(trip.get("TotalDuration")),
        "miles": _int(trip.get("MileageCost")),
        "taxes": round(taxes_cents / 100, 2) if taxes_cents else None,
        "taxes_currency": trip.get("TaxesCurrency") or None,
        "seats": _int(trip.get("RemainingSeats")) or None,
        "booking_link": primary.get("link"),
    }


# ---------- text output ----------

def _money(option: dict) -> str:
    if option.get("taxes") is None:
        return "?"
    return f"{option['taxes']:,.0f} {option.get('taxes_currency') or 'USD'}"


def _row(option: dict) -> str:
    route = f"{option['origin']} to {option['destination']}"
    if option.get("backup_airport"):
        route += " (backup airport)"
    return (
        f"| {option['cabin'].title()} | {option['date']} | {route} | {option['miles']:,} "
        f"| {_money(option)} | {option['seats'] or '?'} | {'yes' if option['nonstop'] else 'no'} "
        f"| {option['airlines'] or '?'} |"
    )


TABLE_HEAD = (
    "| Cabin | Date | Route | Points each | Taxes each | Seats | Nonstop | Airlines |\n"
    "|---|---|---|---|---|---|---|---|"
)


def alert_markdown(new_by_watch: dict[str, list[dict]], settings: dict, details: dict[str, dict]) -> str:
    """The body of the GitHub issue opened when new deals appear."""
    passengers = settings.get("passengers", 1)
    lines = [
        f"New award space that meets the watchlist rules, for {passengers} traveler(s). "
        "Points and taxes are per person, one way.",
        "",
    ]
    for watch_name, deals in new_by_watch.items():
        if not deals:
            continue
        lines += [f"## {watch_name}", "", TABLE_HEAD]
        lines += [_row(d) for d in deals[:15]]
        if len(deals) > 15:
            lines.append(f"\n{len(deals) - 15} more in `data/latest.json`.")
        for deal in deals:
            trip = details.get(deal_key(deal))
            if trip:
                stops = "nonstop" if trip["stops"] == 0 else f"{trip['stops']} stop(s)"
                link = f" [Booking link]({trip['booking_link']})" if trip.get("booking_link") else ""
                lines.append(
                    f"\n- {deal['date']} {deal['cabin']}: flights {trip['flights']}, {stops}, "
                    f"departs {trip['departs']}.{link}"
                )
        lines.append("")
    lines += [
        "---",
        "This comes from seats.aero's cached data, so a seat can be gone by the time you look. "
        "Confirm on alaskaair.com before planning around it. Award data from [seats.aero](https://seats.aero).",
    ]
    return "\n".join(lines)
