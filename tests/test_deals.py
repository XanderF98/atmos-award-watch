import deals
import seats_aero


def outbound(config):
    return config["watches"][0]


def alaska_options(rows, watch):
    return deals.options_for_watch(seats_aero.only_program(rows, "alaska"), watch)


def keys(found):
    return {(d["origin"], d["date"], d["cabin"], d["miles"]) for d in found}


def test_flatten_gives_one_option_per_available_cabin(rows):
    options = deals.flatten(rows[0])
    assert [(o["cabin"], o["miles"]) for o in options] == [("economy", 35000), ("business", 70000)]
    assert options[1]["taxes"] == 56.0 and options[1]["seats"] == 2


def test_watch_ignores_other_airports_and_dates(rows, config):
    options = alaska_options(rows, outbound(config))
    assert all(o["destination"] in outbound(config)["destinations"] for o in options)
    # SEA-LIN on Oct 20 is outside the Oct 1-16 window
    assert not any(o["date"] == "2027-10-20" for o in options)


def test_other_programs_are_excluded(rows, config):
    options = alaska_options(rows, outbound(config))
    assert not any(o["airlines"] == "AC" for o in options)


def test_deal_rules(rows, config):
    watch = outbound(config)
    found = keys(deals.find_deals(alaska_options(rows, watch), watch, config))
    assert ("SEA", "2027-10-02", "business", 70000) in found   # at the limit, 2 seats
    assert ("SEA", "2027-10-03", "economy", 27500) in found    # well under the economy limit
    assert ("SEA", "2027-10-02", "economy", 35000) in found    # under the economy limit
    assert ("SEA", "2027-10-03", "business", 110000) not in found  # too many points
    assert ("SEA", "2027-10-05", "business", 70000) not in found  # only 1 seat for 2 people
    assert ("SEA", "2027-10-06", "business", 70000) not in found  # $610 taxes is over the cap


def test_backup_airport_must_beat_main_airport_by_margin(rows, config):
    watch = outbound(config)
    found = deals.find_deals(alaska_options(rows, watch), watch, config)
    by_origin = {d["origin"]: d for d in found if d["cabin"] == "business"}
    assert by_origin["YVR"]["miles"] == 45000 and by_origin["YVR"]["detour"] == "Vancouver"  # 25k cheaper
    assert "PDX" not in by_origin  # only 10k cheaper than Seattle


def test_backup_airport_counts_when_main_airport_has_nothing(rows, config):
    watch = outbound(config)
    options = [o for o in alaska_options(rows, watch) if o["origin"] != "SEA"]
    found = deals.find_deals(options, watch, config)
    assert {d["origin"] for d in found} == {"YVR", "PDX"}


def test_european_gateway_counts_only_when_it_saves_enough(rows, config):
    watch = outbound(config)
    found = deals.find_deals(alaska_options(rows, watch), watch, config)
    dublin = {d["cabin"]: d for d in found if d["destination"] == "DUB"}
    # Business to Dublin is 55k against 70k to Milan: 15k saved beats the 10k bar.
    assert dublin["business"]["detour"] == "Dublin" and "flight" in dublin["business"]["connection"]
    # Economy to Dublin costs the same as Milan, so the extra hop isn't worth it.
    assert "economy" not in dublin


def test_surcharges_rule_out_a_gateway(rows, config):
    watch = outbound(config)
    found = deals.find_deals(alaska_options(rows, watch), watch, config)
    assert not any(d["destination"] == "LHR" for d in found)  # $980 in taxes is over the $350 cap


def test_two_detours_must_save_both_amounts():
    watch = {"origins": ["SEA", "YVR"], "destinations": ["MXP", "DUB"]}
    settings = {
        "max_miles": {"business": 70000},
        "detours": {"YVR": {"name": "Vancouver", "min_savings": 20000}, "DUB": {"name": "Dublin", "min_savings": 10000}},
    }

    def option(origin, destination, miles):
        return {"origin": origin, "destination": destination, "cabin": "business", "miles": miles,
                "date": "2027-10-02", "seats": 2, "taxes": 50, "taxes_currency": "USD"}

    main = option("SEA", "MXP", 70000)
    assert deals.prefer_main_airports([main, option("YVR", "DUB", 40000)], watch, settings)[-1]["detour"] == "Vancouver and Dublin"
    assert len(deals.prefer_main_airports([main, option("YVR", "DUB", 40001)], watch, settings)) == 1


def test_old_backup_airport_settings_still_work():
    watch = {"backup_airports": ["PDX"]}
    detours = deals.detours_for(watch, {"backup_airport_min_savings": 15000})
    assert detours == {"PDX": {"name": "PDX", "min_savings": 15000}}


def test_unknown_seat_count_is_not_disqualifying(rows, config):
    watch = config["watches"][1]
    found = keys(deals.find_deals(alaska_options(rows, watch), watch, config))
    assert ("FCO", "2027-10-12", "economy", 30000) in found


def test_alerts_only_for_new_or_cheaper_deals(rows, config):
    watch = outbound(config)
    found = deals.find_deals(alaska_options(rows, watch), watch, config)

    new, record = deals.split_new(found, {})
    assert len(new) == len(found) == 5

    new, record = deals.split_new(found, record)
    assert new == []  # same deals the next day: no repeat alert

    cheaper = [{**d, "miles": d["miles"] - 5000} if d["origin"] == "YVR" else d for d in found]
    new, record = deals.split_new(cheaper, record)
    assert [d["origin"] for d in new] == ["YVR"]  # a price drop alerts again

    new, record = deals.split_new(found[:1], record)
    new, _ = deals.split_new(found, record)
    assert len(new) == len(found) - 1  # deals that vanished and came back alert again


def test_cabin_summary(rows, config):
    summary = deals.cabin_summary(alaska_options(rows, outbound(config)))
    assert summary["business"] == {
        "cheapest_miles": 45000, "cheapest_date": "2027-10-02",
        "cheapest_route": "YVR-MXP", "days_available": 5,
    }


def test_describe_trip_picks_the_requested_cabin():
    import json
    from pathlib import Path
    response = json.loads((Path(__file__).parent / "fixtures" / "trips_response.json").read_text())
    trip = deals.describe_trip(response, "business", passengers=2)
    assert trip["miles"] == 70000 and trip["flights"] == "AA 2401, AA 198"
    assert trip["booking_link"] == "https://www.alaskaair.com/"
    assert deals.describe_trip(response, "first") is None
