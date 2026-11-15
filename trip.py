"""Trip-level questions the one-way deal rules can't answer.

  pair_trips        can we get there AND back, and do we have the points?
  release_calendar  which of our dates can be booked yet?
  route_coverage    is the data source returning anything for each airport pair?

Pure functions, like deals.py: no network and no files.
"""

from datetime import date, timedelta

from deals import CABIN_ORDER

RELEASE_WINDOW_DAYS = 331  # Atmos Rewards opens award seats about this far ahead


def _bookable(option: dict, passengers: int) -> bool:
    return option["seats"] is None or option["seats"] >= passengers


def pair_trips(outbound: list[dict], inbound: list[dict], settings: dict) -> list[dict]:
    """Match each way out with a way back and price the whole trip.

    Returns the cheapest pairing for every cabin combination (economy both
    ways, business out and economy back, and so on), cheapest first. Points
    are for all travelers, both directions, and compared with the balance.
    """
    trip = settings.get("trip") or {}
    min_nights, max_nights = trip.get("min_nights", 7), trip.get("max_nights", 14)
    passengers = settings.get("passengers", 1)
    balance = settings.get("points_balance")

    outs = [o for o in outbound if _bookable(o, passengers)]
    backs = [o for o in inbound if _bookable(o, passengers)]

    best: dict[tuple[str, str], dict] = {}
    for out in outs:
        left = date.fromisoformat(out["date"])
        for back in backs:
            nights = (date.fromisoformat(back["date"]) - left).days
            if not min_nights <= nights <= max_nights:
                continue
            total = (out["miles"] + back["miles"]) * passengers
            combo = (out["cabin"], back["cabin"])
            # Cheapest wins; on a tie prefer the trip nearest the middle of the range.
            rank = (total, abs(nights - (min_nights + max_nights) / 2), out["date"])
            if combo not in best or rank < best[combo]["_rank"]:
                best[combo] = {"_rank": rank, "out": out, "back": back, "nights": nights, "total": total}

    trips = []
    for (out_cabin, back_cabin), found in best.items():
        out, back = found["out"], found["back"]
        label = (
            f"{out_cabin.title()} both ways" if out_cabin == back_cabin
            else f"{out_cabin.title()} out, {back_cabin} back"
        )
        taxes = [leg["taxes"] for leg in (out, back)]
        legs = ("id", "origin", "destination", "date", "cabin", "miles", "nonstop", "airlines")
        entry = {
            "label": label,
            "out": {k: out[k] for k in legs},
            "back": {k: back[k] for k in legs},
            "nights": found["nights"],
            "passengers": passengers,
            "total_points": found["total"],
            "total_taxes": round(sum(taxes) * passengers, 2) if None not in taxes else None,
        }
        if balance is not None:
            entry["points_balance"] = balance
            entry["points_short"] = max(0, found["total"] - balance)
        trips.append(entry)

    def comfort(entry: dict) -> int:  # lower = nicer cabins, used to break ties
        return CABIN_ORDER.index(entry["out"]["cabin"]) + CABIN_ORDER.index(entry["back"]["cabin"])

    return sorted(trips, key=lambda t: (t["total_points"], comfort(t)))


def release_calendar(watch: dict, today: date, window_days: int = RELEASE_WINDOW_DAYS) -> dict:
    """Which dates in a watch are inside the booking window, and when the rest open."""
    start, end = date.fromisoformat(watch["start_date"]), date.fromisoformat(watch["end_date"])
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    horizon = today + timedelta(window_days)  # last travel date that can be booked today
    open_days = [d for d in days if d <= horizon]
    waiting = [d for d in days if d > horizon]
    return {
        "dates_total": len(days),
        "dates_open": len(open_days),
        "open_through": open_days[-1].isoformat() if open_days else None,
        "next_date": waiting[0].isoformat() if waiting else None,
        "next_opens_on": (waiting[0] - timedelta(window_days)).isoformat() if waiting else None,
        "all_open_on": (end - timedelta(window_days)).isoformat() if waiting else None,
    }


def route_coverage(rows: list[dict], watch: dict) -> dict[str, int]:
    """How many days of data came back for each airport pair in a watch.

    Zero for a pair usually means the data source does not track that route
    (it mostly tracks pairs with a nonstop flight), not that seats are sold out.
    """
    counts = {f"{o}-{d}": 0 for o in watch["origins"] for d in watch["destinations"]}
    for row in rows:
        route = row.get("Route") or {}
        pair = f"{route.get('OriginAirport')}-{route.get('DestinationAirport')}"
        if pair in counts:
            counts[pair] += 1
    return counts
