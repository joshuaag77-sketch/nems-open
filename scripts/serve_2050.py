"""Serve web/ locally and let "Your America in 2050" run the real model.

    python scripts/serve_2050.py [--port 8050]

Then open http://localhost:8050/2050.html. Static files come from web/. Two endpoints:

    POST /api/run         {"levers": {...}}  starts a run (one at a time), returns {"id": ...}
    GET  /api/run/<id>    {"status": "running" | "done" | "failed", "elapsed_s", "result"?, "error"?}
    GET  /api/health      {"ok": true, "ported": [...], "ask": true when ANTHROPIC_API_KEY is set}
    POST /api/ask         {"question": "..."}  runs the policy agent (src/nems_open/agent) and returns
                          {"body", "sources", "basis", "declined", "apply", "unmapped", ...}. One at a time.
                          Needs ANTHROPIC_API_KEY in the environment; the key is read there and never sent
                          to the page, logged or stored. Without it: 503 {"error": "no_key"}.

A run is run_model.run with residential, commercial and transportation through EIA's ported
routines and supply on the stand-in, 2027-2050. Each lever's grade for that run comes from
nems_open.levers.fidelity. Local only: it binds to 127.0.0.1 and the Vercel preview has no
server, so the page's button says the real model needs this script.
"""

import argparse
import json
import os
import sys
import threading
import time
import traceback
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_ux2050 as ux  # noqa: E402

WEB = ROOT / "web"
PORTED = ("residential", "commercial", "transportation")
ELEC = "standin"
LEVER_NAMES = ("carbon_price", "ev_2035", "load_growth", "coal_retirement", "renewable_cost", "gas_supply",
               "oil_price", "nuclear", "building_code", "appliance_standard")
LIMITS = {"carbon_price": (0, 500), "ev_2035": (0, 1), "load_growth": (0, 2000), "coal_retirement": (0, 1),
          "renewable_cost": (-1, 1), "gas_supply": (-1, 1), "oil_price": (0.25, 3), "nuclear": (0, 2),
          "building_code": (0, 0.6), "appliance_standard": (0, 0.6)}

JOBS: dict[str, dict] = {}
BUSY = threading.Lock()
ASKING = threading.Lock()
MAX_QUESTION = 600


def make_agent():
    """The policy agent on the real API (key from the environment). Tests replace this with a scripted stub."""
    from nems_open.agent import PolicyAgent
    return PolicyAgent()


def page_levers(runs: list) -> tuple[dict, list]:
    """The page's lever settings for the scenario the agent ran. The agent now uses the page's own lever names and its
    own instant estimate, so this is a pass-through of the last scenario that moves anything (else the last one)."""
    if not runs:
        return {}, []
    run = ([r for r in runs if r] or runs)[-1]
    return {k: v for k, v in run.items() if k in LEVER_NAMES}, []


MAX_BODY = 4096


def friendly(e: Exception) -> str:
    """A plain sentence for a failure of the model service. Never the exception text (it can carry request details)."""
    n = type(e).__name__
    if "Authentication" in n or "PermissionDenied" in n:
        return "The model service rejected this server's API key. Check the key and restart the server."
    if "RateLimit" in n or "Overloaded" in n or "InternalServer" in n:
        return "The model service is busy right now. Try again in a minute."
    if "Timeout" in n or "Connection" in n:
        return "The model service could not be reached. Check the internet connection and try again."
    return "Something went wrong while answering. Try again; if it keeps happening, check the server window."


def ask(question: str) -> tuple[int, dict]:
    """(status, body) for one question. All errors are plain text; nothing here prints or returns the API key."""
    q = (question or "").strip()
    if not q:
        return 400, {"error": "bad_request", "message": "Type a question first."}
    if len(q) > MAX_QUESTION:
        return 400, {"error": "bad_request", "message": f"Keep the question under {MAX_QUESTION} characters."}
    if not ASKING.acquire(blocking=False):
        return 409, {"error": "busy", "message": "Another question is being answered. Try again in a minute."}
    try:
        a = make_agent().ask(q)
    except RuntimeError as e:          # make_client: no key
        if "ANTHROPIC_API_KEY" in str(e):
            return 503, {"error": "no_key", "message": "No ANTHROPIC_API_KEY is set for this server, so questions cannot be answered."}
        traceback.print_exc()
        return 502, {"error": "agent", "message": friendly(e)}
    except Exception as e:             # network, API status, SDK
        traceback.print_exc()
        return 502, {"error": "agent", "message": friendly(e)}
    finally:
        ASKING.release()
    apply, unmapped = page_levers(a.runs)
    return 200, {"body": a.body or a.text, "declined": a.declined, "error": a.error, "outside": a.outside,
                 "sources": [{"markers": s["markers"], "grade": s["grade"], "grade_label": s["grade_label"],
                              "line": s["line"]} for s in a.sources],
                 "basis": a.basis, "apply": apply, "unmapped": unmapped, "stand_in": a.stand_in,
                 "model": a.model, "tokens": {"in": a.input_tokens, "out": a.output_tokens}}


def clean(levers: dict) -> dict:
    out = {}
    for k, v in (levers or {}).items():
        if k not in LEVER_NAMES or v is None:
            continue
        lo, hi = LIMITS[k]
        out[k] = min(max(float(v), lo), hi)
    return out


def grades(x: dict) -> dict:
    from nems_open import levers
    name = {"ev_2035": "ev_share"}
    return {k: dict(zip(("grade", "why"), levers.fidelity(name.get(k, k), PORTED, ELEC))) for k in LEVER_NAMES}


def work(job: dict) -> None:
    from nems_open import run_model
    from nems_open.supply_standin.data import load_case
    x = job["levers"]
    t0 = time.time()
    try:
        pol = ux.policy(x, x.get("building_code", 0.0), x.get("appliance_standard", 0.0))
        r = run_model.run(pol, ux.START, 2050, ported=PORTED, elec=ELEC)
        out = ux.outputs(r.prices, r.quantities, r.co2, load_case("cb2026"), ux.households())
        job["result"] = {k: [round(float(v), 4) for v in a] for k, a in out.items()}
        job["converged"] = {str(y): bool(s) for y, s in r.stable.items()}
        job["status"] = "done"
    except Exception as e:
        job["status"] = "failed"
        job["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    finally:
        job["elapsed_s"] = round(time.time() - t0, 1)
        BUSY.release()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WEB), **k)

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(200, {"ok": True, "ported": list(PORTED), "elec": ELEC,
                                    "ask": bool(os.environ.get("ANTHROPIC_API_KEY"))})
        if self.path.startswith("/api/run/"):
            job = JOBS.get(self.path.rsplit("/", 1)[-1])
            if not job:
                return self._json(404, {"error": "no such run"})
            body = {k: v for k, v in job.items() if k != "started"}
            if job["status"] == "running":
                body["elapsed_s"] = round(time.time() - job["started"], 1)
            return self._json(200, body)
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/ask":
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > MAX_BODY:
                return self._json(413, {"error": "too_large", "message": "That request is too large."})
            try:
                q = json.loads(self.rfile.read(n) or b"{}").get("question")
            except (ValueError, AttributeError):
                return self._json(400, {"error": "bad_request", "message": "body must be JSON with a question"})
            if not isinstance(q, str):
                return self._json(400, {"error": "bad_request", "message": "body must be JSON with a question"})
            return self._json(*ask(q))
        if self.path != "/api/run":
            return self._json(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            levers = clean(json.loads(self.rfile.read(n) or b"{}").get("levers"))
        except (ValueError, AttributeError):
            return self._json(400, {"error": "body must be JSON with a levers object"})
        if not BUSY.acquire(blocking=False):
            return self._json(409, {"error": "a run is already going; one at a time"})
        jid = uuid.uuid4().hex[:10]
        JOBS[jid] = {"id": jid, "status": "running", "levers": levers, "started": time.time(),
                     "ported": list(PORTED), "elec": ELEC, "grades": grades(levers)}
        threading.Thread(target=work, args=(JOBS[jid],), daemon=True).start()
        return self._json(202, {"id": jid})

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):
            super().log_message(fmt, *args)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8050)
    a = ap.parse_args(argv)
    print(f"http://localhost:{a.port}/2050.html", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
