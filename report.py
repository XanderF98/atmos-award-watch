"""The dashboard the daily job writes: a Markdown page and a small SVG chart."""

from datetime import date
from xml.sax.saxutils import escape

SOURCE_NOTE = "Award data from [seats.aero](https://seats.aero)"


def _d(day: str) -> str:
    return date.fromisoformat(day).strftime("%b %-d")


def _leg(leg: dict) -> str:
    stops = "nonstop" if leg["nonstop"] else "connecting"
    return f"{_d(leg['date'])} {leg['origin']}-{leg['destination']} ({leg['cabin']}, {leg['miles']:,}, {stops})"


def trips_table(trips: list[dict]) -> list[str]:
    if not trips:
        return ["No way out and back fits the trip length yet."]
    balance = trips[0].get("points_balance")
    head = "| Option | Out | Back | Nights | Points for {n} | Taxes | {b} |".format(
        n=trips[0]["passengers"],
        b=f"Against {balance:,}" if balance is not None else "Balance",
    )
    lines = [head, "|---|---|---|---|---|---|---|"]
    for trip in trips[:6]:
        if balance is None:
            verdict = "not set"
        elif trip["points_short"]:
            verdict = f"{trip['points_short']:,} short"
        else:
            verdict = f"covered, {balance - trip['total_points']:,} left"
        taxes = f"${trip['total_taxes']:,.0f}" if trip["total_taxes"] is not None else "?"
        lines.append(
            f"| {trip['label']} | {_leg(trip['out'])} | {_leg(trip['back'])} | {trip['nights']} "
            f"| {trip['total_points']:,} | {taxes} | {verdict} |"
        )
    return lines


def release_line(name: str, release: dict) -> str:
    if release["dates_open"] == release["dates_total"]:
        return f"- **{name}:** all {release['dates_total']} dates can be booked."
    if release["dates_open"] == 0:
        return (
            f"- **{name}:** none of the {release['dates_total']} dates can be booked yet. "
            f"The first opens {_d(release['next_opens_on'])}, the last {_d(release['all_open_on'])}."
        )
    return (
        f"- **{name}:** {release['dates_open']} of {release['dates_total']} dates can be booked "
        f"(through {_d(release['open_through'])}). {_d(release['next_date'])} opens "
        f"{_d(release['next_opens_on'])}; all are open by {_d(release['all_open_on'])}."
    )


def coverage_line(name: str, coverage: dict[str, int]) -> str:
    seen = [pair for pair, count in coverage.items() if count]
    silent = [pair for pair, count in coverage.items() if not count]
    line = f"- **{name}:** data for {', '.join(seen) if seen else 'no routes'}."
    if silent:
        line += f" Nothing returned for {', '.join(silent)}."
    return line


def dashboard_markdown(snapshot: dict, chart_file: str | None = "chart.svg") -> str:
    """The whole latest check as one readable page."""
    lines = [
        "# Latest award check",
        "",
        f"Checked {snapshot['generated_at'][:16].replace('T', ' ')} UTC for "
        f"{snapshot['passengers']} traveler(s). {SOURCE_NOTE}; it is cached, so confirm on "
        "alaskaair.com before acting.",
        "",
        "## Can we book the whole trip?",
        "",
        *trips_table(snapshot.get("trips", [])),
        "",
    ]
    if chart_file:
        lines += [f"![Cheapest round trip over time]({chart_file})", ""]
    lines += ["## Which dates can be booked yet?", ""]
    lines += [release_line(w["name"], w["release"]) for w in snapshot["watches"]]
    lines += ["", "## Is the data source covering our routes?", ""]
    lines += [coverage_line(w["name"], w["coverage"]) for w in snapshot["watches"]]
    lines += [
        "",
        "A route with nothing returned is usually one seats.aero does not track, "
        "not one that is sold out.",
        "",
        "## Cheapest one-way price by cabin",
        "",
    ]
    for watch in snapshot["watches"]:
        lines.append(f"**{watch['name']}** ({len(watch['deals'])} deals meeting the rules)")
        lines.append("")
        if not watch["cabins"]:
            lines += ["No award space found.", ""]
            continue
        lines += ["| Cabin | Points each | On | Route | Days with space |", "|---|---|---|---|---|"]
        for cabin, s in watch["cabins"].items():
            lines.append(
                f"| {cabin.title()} | {s['cheapest_miles']:,} | {_d(s['cheapest_date'])} "
                f"| {s['cheapest_route']} | {s['days_available']} |"
            )
        lines.append("")
    return "\n".join(lines)


def chart_svg(series: dict[str, list[tuple[str, int]]], balance: int | None = None) -> str:
    """A line chart of points over time, one line per series, as standalone SVG.

    series maps a label to (run_date, points) pairs. Drawn by hand so the daily
    job needs no plotting library.
    """
    width, height, left, right, top, bottom = 780, 300, 64, 210, 28, 40
    colors = ["#2f81f7", "#d29922", "#3fb950", "#db61a2", "#a371f7", "#8b949e"]
    dates = sorted({day for points in series.values() for day, _ in points})
    values = [value for points in series.values() for _, value in points]
    if balance is not None:
        values.append(balance)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'font-family="system-ui, sans-serif" font-size="12" role="img" '
        f'aria-label="Cheapest round trip in points over time">',
        f'<text x="{left}" y="16" fill="#8b949e">Cheapest round trip, total points</text>',
    ]
    if not values:
        out.append(f'<text x="{left}" y="{height / 2}" fill="#8b949e">No data yet</text></svg>')
        return "\n".join(out)

    low, high = min(values), max(values)
    pad = max((high - low) * 0.15, 5000)
    low, high = max(0, low - pad), high + pad
    plot_w, plot_h = width - left - right, height - top - bottom

    def x(day: str) -> float:
        if len(dates) == 1:
            return left + plot_w / 2
        return left + plot_w * dates.index(day) / (len(dates) - 1)

    def y(value: float) -> float:
        return top + plot_h * (1 - (value - low) / (high - low))

    for step in range(5):
        value = low + (high - low) * step / 4
        out.append(
            f'<line x1="{left}" x2="{left + plot_w}" y1="{y(value):.1f}" y2="{y(value):.1f}" '
            f'stroke="#8b949e" stroke-opacity="0.25"/>'
            f'<text x="{left - 8}" y="{y(value) + 4:.1f}" text-anchor="end" fill="#8b949e">'
            f"{value / 1000:.0f}k</text>"
        )
    for day in {dates[0], dates[-1]}:
        out.append(
            f'<text x="{x(day):.1f}" y="{height - 14}" text-anchor="middle" fill="#8b949e">'
            f"{escape(_d(day))}</text>"
        )
    if balance is not None:
        out.append(
            f'<line x1="{left}" x2="{left + plot_w}" y1="{y(balance):.1f}" y2="{y(balance):.1f}" '
            f'stroke="#f85149" stroke-dasharray="6 4"/>'
        )
    labels = []  # (y position, color, text) for the right-hand legend
    for index, (label, points) in enumerate(series.items()):
        color = colors[index % len(colors)]
        points = sorted(points)
        path = " ".join(f"{x(day):.1f},{y(value):.1f}" for day, value in points)
        if len(points) > 1:
            out.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2"/>')
        for day, value in points:
            out.append(f'<circle cx="{x(day):.1f}" cy="{y(value):.1f}" r="3.5" fill="{color}"/>')
        labels.append((y(points[-1][1]) + 4, color, label))
    if balance is not None:
        labels.append((y(balance) + 4, "#f85149", f"our balance {balance / 1000:.0f}k"))
    previous = None
    for position, color, text in sorted(labels):  # nudge labels apart so none overlap
        if previous is not None and position - previous < 15:
            position = previous + 15
        previous = position
        out.append(f'<text x="{left + plot_w + 8}" y="{position:.1f}" fill="{color}">{escape(text)}</text>')
    out.append("</svg>")
    return "\n".join(out)
