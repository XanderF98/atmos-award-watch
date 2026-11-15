import xml.dom.minidom
from datetime import date

import deals
import report
import seats_aero
import trip
import watcher


def snapshot_for(rows, config, today=date(2026, 11, 15)):
    return watcher.check(config, search=lambda *a, **k: seats_aero.only_program(rows, "alaska"), today=today)


def test_pairs_cheapest_way_out_with_a_way_back(rows, config):
    trips = snapshot_for(rows, config)["trips"]
    cheapest = trips[0]
    assert cheapest["label"] == "Economy both ways"
    assert (cheapest["out"]["date"], cheapest["back"]["date"], cheapest["nights"]) == ("2027-10-03", "2027-10-12", 9)
    assert cheapest["total_points"] == (27500 + 30000) * 2  # two travelers, both directions
    assert cheapest["points_short"] == 115000 - 91000
    assert cheapest["total_taxes"] == (56 + 91) * 2


def test_pairs_respect_trip_length(rows, config):
    config["trip"].update(min_nights=11, max_nights=12)
    trips = snapshot_for(rows, config)["trips"]
    assert trips and all(11 <= t["nights"] <= 12 for t in trips)
    config["trip"].update(min_nights=20, max_nights=25)
    assert snapshot_for(rows, config)["trips"] == []


def test_pairs_skip_flights_without_enough_seats(rows, config):
    # The Oct 5 business seat has 1 seat for 2 people, so it must never be used.
    trips = snapshot_for(rows, config)["trips"]
    assert not any(t["out"]["date"] == "2027-10-05" for t in trips)


def test_pairs_use_backup_airport_only_when_it_saves_enough(rows, config):
    by_label = {t["label"]: t for t in snapshot_for(rows, config)["trips"]}
    assert by_label["Business out, economy back"]["out"]["origin"] == "YVR"  # 25k cheaper than Seattle
    config["detours"]["YVR"]["min_savings"] = 30000
    out = {t["label"]: t for t in snapshot_for(rows, config)["trips"]}["Business out, economy back"]["out"]
    # Vancouver no longer saves enough, so the next best is Seattle to Dublin.
    assert (out["origin"], out["destination"], out["detour"]) == ("SEA", "DUB", "Dublin")


def test_covered_when_balance_is_enough(rows, config):
    config["points_balance"] = 120000
    cheapest = snapshot_for(rows, config)["trips"][0]
    assert cheapest["points_short"] == 0
    assert "covered, 5,000 left" in "\n".join(report.trips_table([cheapest]))


def test_release_calendar_counts_dates_inside_the_booking_window(config):
    watch = config["watches"][1]  # Oct 10 to Oct 28, 2027
    release = trip.release_calendar(watch, date(2026, 11, 15))
    assert release == {
        "dates_total": 19, "dates_open": 3, "open_through": "2027-10-12",
        "next_date": "2027-10-13", "next_opens_on": "2026-11-16", "all_open_on": "2026-12-01",
    }
    assert trip.release_calendar(watch, date(2026, 10, 1))["dates_open"] == 0
    done = trip.release_calendar(watch, date(2026, 12, 1))
    assert done["dates_open"] == 19 and done["next_opens_on"] is None


def test_route_coverage_flags_pairs_with_no_data(rows, config):
    coverage = trip.route_coverage(seats_aero.only_program(rows, "alaska"), config["watches"][0])
    assert coverage["SEA-MXP"] == 4 and coverage["YVR-MXP"] == 1
    assert coverage["SEA-FCO"] == 0  # nothing came back for this pair


def test_headline_is_the_deal_furthest_under_its_limit(rows, config):
    watch = config["watches"][0]
    options = deals.options_for_watch(seats_aero.only_program(rows, "alaska"), watch)
    best = deals.headline(deals.find_deals(options, watch, config), config["max_miles"])
    assert (best["origin"], best["cabin"], best["miles"]) == ("YVR", "business", 45000)


def test_dashboard_and_chart_render(rows, config):
    snapshot = snapshot_for(rows, config)
    page = report.dashboard_markdown(snapshot)
    assert "24,000 short" in page
    assert "3 of 19 dates can be booked (through Oct 12)" in page
    assert "Nothing returned for SEA-FCO" in page
    assert "seats.aero" in page  # the data source must be credited

    history = [
        {"run_date": "2026-11-14", "option": "Economy both ways", "total_points": "120000"},
        {"run_date": "2026-11-15", "option": "Economy both ways", "total_points": "115000"},
        {"run_date": "2026-11-15", "option": "Business both ways & more", "total_points": "260000"},
    ]
    svg = report.chart_svg(watcher.chart_series(history), balance=91000)
    xml.dom.minidom.parseString(svg)  # must be well-formed
    assert "our balance 91k" in svg and "Business both ways &amp; more" in svg
    xml.dom.minidom.parseString(report.chart_svg({}, balance=None))


def test_landing_comparison_shows_where_a_detour_pays_off(rows, config):
    snapshot = snapshot_for(rows, config)
    out, back = (w["landing"] for w in snapshot["watches"])
    dublin = next(r for r in out if r["airport"] == "DUB")
    assert dublin["cheapest"] == {"economy": 27500, "business": 55000}
    assert dublin["compared"]["business"] == {"saves": 15000, "worth_it": True}
    assert dublin["compared"]["economy"] == {"saves": 0, "worth_it": False}
    london = next(r for r in out if r["airport"] == "LHR")
    assert london["cheapest"] == {}  # only a seat with surcharges over the cap
    assert out[0]["airport"] == "MXP" and not out[0]["detour"]  # Italy first
    assert next(r for r in back if r["airport"] == "DUB")["compared"]["business"]["saves"] == 30000

    page = report.dashboard_markdown(snapshot)
    assert "Is it cheaper to land somewhere else in Europe?" in page
    assert "business saves 15,000 (yes)" in page
    assert "Nothing bookable yet at Rome (FCO)" in page
