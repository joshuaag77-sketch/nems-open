"""GET /api/health on Vercel: whether the Ask box can answer here. No real-run server on the host ("run": false)."""

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nems_open.agent import hosted  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps(hosted.health()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
