import csv
import json
import sys

import pytest

import seats_aero
import watcher


def run(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys, "argv",
        ["watcher.py", "--data-dir", str(tmp_path), "--alert-file", str(tmp_path / "alert.md")],
    )
    return watcher.main()


def test_client_sends_key_follows_pages_and_filters_program(api):
    rows = seats_aero.search(["SEA", "YVR", "PDX"], ["MXP", "LIN"], "2027-10-01", "2027-10-16")
    assert len(rows) == 12  # 13 in the fixture, one from another program
    assert len(api.calls) == 4  # 13 rows at 4 per page
    assert "sources=alaska" in api.calls[0] and "origin_airport=SEA%2CYVR%2CPDX" in api.calls[0]


def test_client_explains_a_bad_key(api, monkeypatch):
    monkeypatch.setenv("SEATS_AERO_API_KEY", "wrong")
    with pytest.raises(seats_aero.SeatsAeroError, match="API key was rejected"):
        seats_aero.search(["SEA"], ["MXP"], "2027-10-01", "2027-10-16")


def test_client_explains_a_missing_key(monkeypatch):
    monkeypatch.delenv("SEATS_AERO_API_KEY", raising=False)
    with pytest.raises(seats_aero.SeatsAeroError, match="SEATS_AERO_API_KEY is not set"):
        seats_aero.trips("abc")


def test_full_run_saves_results_and_alerts_once(api, monkeypatch, tmp_path):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert run(monkeypatch, tmp_path) == 0
    snapshot = json.loads((tmp_path / "latest.json").read_text())
    assert [len(w["deals"]) for w in snapshot["watches"]] == [5, 4]
    alert = (tmp_path / "alert.md").read_text()
    assert "YVR to MXP (via Vancouver)" in alert and "flights AA 2401, AA 198" in alert
    assert "Via Dublin: a 2.5 to 3 hour flight to or from Italy. That part is booked separately." in alert
    assert alert.startswith("## The whole trip right now") and "24,000 short" in alert
    assert "new_deals=9" in output.read_text()
    assert "business YVR-MXP for 45,000 points" in output.read_text()  # headline, not just first class
    assert "24,000 short" in (tmp_path / "README.md").read_text()
    assert (tmp_path / "chart.svg").read_text().startswith("<svg")

    # Second run the same day: nothing new, no duplicate history rows.
    (tmp_path / "alert.md").unlink()
    output.write_text("")
    assert run(monkeypatch, tmp_path) == 0
    assert not (tmp_path / "alert.md").exists()
    assert "new_deals=0" in output.read_text()
    with (tmp_path / "history.csv").open() as handle:
        history = list(csv.DictReader(handle))
    assert len(history) == 6  # 2 cabins outbound + 4 cabins return, once
    assert {"watch": "Seattle to Europe", "cabin": "business", "cheapest_miles": "45000"}.items() <= history[0].items()


def test_run_fails_loudly_when_the_api_rejects_the_key(api, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SEATS_AERO_API_KEY", "wrong")
    assert run(monkeypatch, tmp_path) == 1
    assert "API key was rejected" in capsys.readouterr().err
    assert not (tmp_path / "latest.json").exists()


def test_check_routes_reports_untracked_pairs(api, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["watcher.py", "--check-routes"])
    assert watcher.main() == 0
    out = capsys.readouterr().out
    assert "SEA-MXP: tracked (4 days of data" in out
    assert "SEA-FCO: NOT tracked" in out and "will never alert" in out
