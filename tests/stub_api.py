"""A stand-in for the seats.aero API, serving the fixture files over HTTP.

Used by the tests, and handy for trying the watcher and server without a key:

  python tests/stub_api.py 8765
  SEATS_AERO_BASE_URL=http://127.0.0.1:8765/partnerapi SEATS_AERO_API_KEY=test-key python watcher.py
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_SIZE = 4  # small, so pagination is exercised


class Handler(BaseHTTPRequestHandler):
    calls: list[str] = []

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        Handler.calls.append(self.path)
        if self.headers.get("Partner-Authorization") != "test-key":
            return self._send(401, {})
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == "/partnerapi/search":
            rows = json.loads((FIXTURES / "search_response.json").read_text())["data"]
            skip = int(query.get("skip", ["0"])[0])
            page = rows[skip : skip + PAGE_SIZE]
            return self._send(
                200,
                {"data": page, "count": len(page), "hasMore": skip + PAGE_SIZE < len(rows), "cursor": 1},
            )
        if url.path.startswith("/partnerapi/trips/"):
            return self._send(200, json.loads((FIXTURES / "trips_response.json").read_text()))
        self._send(404, {})


def serve(port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    server = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
    print(f"Stub seats.aero API on http://127.0.0.1:{server.server_port}/partnerapi (key: test-key)")
    server.serve_forever()
