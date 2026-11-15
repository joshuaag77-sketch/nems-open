"""POST /api/ask on Vercel: the policy agent behind the limits in nems_open.agent.hosted. The key stays in the env."""

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nems_open.agent import hosted  # noqa: E402

MAX_BODY = 4096


def client_ip(headers) -> str:
    """Vercel sets x-forwarded-for to the visitor's address (it overwrites any value the visitor sends)."""
    return (headers.get("x-forwarded-for") or headers.get("x-real-ip") or "").split(",")[0].strip()


class handler(BaseHTTPRequestHandler):
    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > MAX_BODY:
            return self._json(413, {"error": "too_large", "message": "That request is too large."})
        try:
            q = json.loads(self.rfile.read(n) or b"{}").get("question")
        except (ValueError, AttributeError):
            q = None
        if not isinstance(q, str):
            return self._json(400, {"error": "bad_request", "message": "Send JSON with a question."})
        return self._json(*hosted.answer(q, client_ip(self.headers)))

    def do_GET(self):
        return self._json(405, {"error": "method", "message": "Use POST."})
