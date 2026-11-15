import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import stub_api  # noqa: E402


# Tests use a frozen copy of the watchlist, so editing the real one never breaks them.
CONFIG_PATH = ROOT / "tests" / "fixtures" / "watchlist.json"


@pytest.fixture()
def config():
    return json.loads(CONFIG_PATH.read_text())


@pytest.fixture()
def rows():
    return json.loads((ROOT / "tests" / "fixtures" / "search_response.json").read_text())["data"]


@pytest.fixture()
def api(monkeypatch):
    """A running stub API, with the client pointed at it."""
    server = stub_api.serve()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stub_api.Handler.calls.clear()
    monkeypatch.setenv("SEATS_AERO_BASE_URL", f"http://127.0.0.1:{server.server_port}/partnerapi")
    monkeypatch.setenv("SEATS_AERO_API_KEY", "test-key")
    yield stub_api.Handler
    server.shutdown()
