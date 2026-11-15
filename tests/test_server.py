import asyncio
import json
import sys

import pytest

pytest.importorskip("mcp")

import server  # noqa: E402
import watcher  # noqa: E402


@pytest.fixture()
def saved_results(api, monkeypatch, tmp_path):
    """Run the watcher once against the stub API and point the server at the results."""
    monkeypatch.setattr(
        sys, "argv", ["watcher.py", "--data-dir", str(tmp_path / "data"), "--alert-file", str(tmp_path / "a.md")]
    )
    assert watcher.main() == 0
    for name in ("latest.json", "history.csv"):
        (tmp_path / "data" / name).read_text()
    monkeypatch.setattr(server, "read_data", lambda name: (tmp_path / "data" / name).read_text())
    server._cache.clear()
    server._live_calls.update(day="", count=0)
    return api


def test_trip_options_report_the_shortfall(saved_results):
    result = server.get_trip_options()
    assert result["trips"][0]["points_short"] == 24000
    assert set(result["dates_open_for_booking"]) == {"Seattle to Europe", "Europe to Seattle"}


def test_current_deals_can_filter_by_cabin(saved_results):
    result = server.get_current_deals("business")
    cabins = {d["cabin"] for w in result["watches"] for d in w["deals"]}
    assert cabins == {"business"}
    assert "error" in server.get_current_deals("cargo")


def test_price_history_tracks_lowest_seen(saved_results):
    result = server.get_price_history("business")
    assert result["series"]["Seattle to Europe / business"]["lowest_seen"] == 45000


def test_live_search_validates_input_before_spending_a_call(saved_results):
    before = len(saved_results.calls)
    assert "error" in server.search_awards("Seattle", "MXP", "2027-10-01", "2027-10-10")
    assert "error" in server.search_awards("SEA", "MXP", "2027-10-01", "2028-03-01")
    assert len(saved_results.calls) == before


def test_live_search_is_cached_and_capped(saved_results, monkeypatch):
    first = server.search_awards("SEA,YVR", "MXP", "2027-10-01", "2027-10-10", cabin="business")
    assert first["cheapest_by_cabin"]["business"]["cheapest_miles"] == 45000
    calls = len(saved_results.calls)
    server.search_awards("SEA,YVR", "MXP", "2027-10-01", "2027-10-10", cabin="economy")
    assert len(saved_results.calls) == calls  # same route and dates: served from the cache

    monkeypatch.setattr(server, "LIVE_CALL_DAILY_LIMIT", 1)
    blocked = server.search_awards("SEA", "LIN", "2027-10-01", "2027-10-10")
    assert "limit" in blocked["error"]


def test_flight_details_respect_the_number_of_travelers(saved_results):
    details = server.get_flight_details("avail001", "business")
    assert details["flights"] == "AA 2401, AA 198" and details["seats"] == 2


def test_requests_without_the_key_are_refused():
    sent = []

    async def app(scope, receive, send):
        sent.append("reached the app")

    async def send(message):
        sent.append(message)

    guarded = server.require_api_key(app, "secret")
    scope = {"type": "http", "headers": [(b"x-api-key", b"wrong")]}
    asyncio.run(guarded(scope, None, send))
    assert sent[0]["status"] == 401 and "reached the app" not in sent

    sent.clear()
    scope = {"type": "http", "headers": [(b"x-api-key", b"secret")]}
    asyncio.run(guarded(scope, None, send))
    assert sent == ["reached the app"]
