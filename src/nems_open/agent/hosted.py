"""The Ask box on a public host: the policy agent behind hard limits on who can ask, how much, and what it may cost.

    status, body = answer(question, ip)          # api/ask.py calls this; so do the tests, with a fake store and client

Every limit is read from the environment, with a safe default, so changing one is a setting, not a code change:

    ASK_ENABLED        "1" to answer (default "0": off until switched on)
    ASK_MODEL          model id (default claude-haiku-5-5, the cheapest; docs/hosting.md says when to raise it)
    ASK_EFFORT         thinking effort (default "low")
    ASK_MAX_TOKENS     output cap per model call (default 4000)
    ASK_MAX_OUTPUT     output cap summed over one question (default 12000)
    ASK_MAX_TURNS      model calls per question (default 8)
    ASK_PER_IP_HOUR    questions per visitor per hour (default 5)
    ASK_PER_IP_DAY     questions per visitor per day (default 15)
    ASK_PER_MINUTE     questions per minute from everyone together (default 10)
    ASK_DAILY_USD      spend ceiling per UTC day, in dollars (default 2)

The counters live in a Redis store reached over HTTPS (Upstash, from the Vercel Marketplace), so they hold across
function instances: KV_REST_API_URL and KV_REST_API_TOKEN, or UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN.
Without a store, or if it cannot be reached, nothing is answered (fails closed). Visitors are counted by a hash of
their IP; the IP itself is never stored. The API key is read by the SDK from ANTHROPIC_API_KEY and never leaves the
function. The daily ceiling is checked before each question with a reserve for that question, then settled with its
real cost, so concurrent questions cannot together run far past it. A spend limit on the Anthropic workspace that
holds the key is the backstop behind all of this (docs/hosting.md).
"""

import hashlib
import json
import os
import time
import urllib.request

from nems_open.agent import rules
from nems_open.agent.loop import PolicyAgent

MAX_QUESTION = 600

# dollars per million tokens: (input, output). Cache reads cost 0.1x input, cache writes 1.25x input.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def setting(name: str, default):
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return type(default)(raw)
    except ValueError:
        return default


def limits() -> dict:
    return {
        "enabled": setting("ASK_ENABLED", "0") == "1",
        "model": setting("ASK_MODEL", "claude-haiku-5-5"),
        "effort": setting("ASK_EFFORT", "low"),
        "max_tokens": setting("ASK_MAX_TOKENS", 4000),
        "max_output": setting("ASK_MAX_OUTPUT", 12000),
        "max_turns": setting("ASK_MAX_TURNS", 8),
        "per_ip_hour": setting("ASK_PER_IP_HOUR", 5),
        "per_ip_day": setting("ASK_PER_IP_DAY", 15),
        "per_minute": setting("ASK_PER_MINUTE", 10),
        "daily_usd": setting("ASK_DAILY_USD", 2.0),
    }


def cost_usd(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])     # an unknown model is priced as the dearest listed
    return (inp * pin + cache_read * pin * 0.1 + cache_write * pin * 1.25 + out * pout) / 1e6


def worst_case_usd(lim: dict) -> float:
    """What one question can cost at most under these limits: every turn resends a context that has grown by every
    earlier turn's output plus tool results (allowed 6,000 tokens each), all uncached, and the output cap is spent."""
    turns, per_out = lim["max_turns"], lim["max_tokens"]
    base = 9000                                                 # system prompt and tool schemas, rounded up
    inp = sum(base + k * (per_out + 6000) for k in range(turns))
    return cost_usd(lim["model"], inp, min(lim["max_output"] + per_out, turns * per_out))


class RestStore:
    """The few Redis commands the limits need, over the Upstash REST API (one HTTPS call per pipeline)."""

    def __init__(self, url: str, token: str):
        self.url, self.token = url.rstrip("/"), token

    @classmethod
    def from_env(cls):
        url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
        token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
        return cls(url, token) if url and token else None

    def pipeline(self, commands: list[list]) -> list:
        req = urllib.request.Request(self.url + "/pipeline", data=json.dumps(commands).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            out = json.loads(r.read())
        if any("error" in x for x in out):
            raise RuntimeError("store error")
        return [x.get("result") for x in out]


def visitor(ip: str) -> str:
    return hashlib.sha256(("nems-open:" + (ip or "unknown")).encode()).hexdigest()[:16]


def _counter(key: str, ttl: int) -> list[list]:
    return [["SET", key, 0, "EX", ttl, "NX"], ["INCR", key]]     # creates with an expiry once, then counts


def admit(store, ip: str, lim: dict, now: float | None = None) -> tuple[str | None, str]:
    """(None, spend key) when this visitor may ask now, else (reason, ""). Counts the attempt and reserves its worst
    case against the day's ceiling."""
    t = int(now if now is not None else time.time())
    day, hour, minute, v = t // 86400, t // 3600, t // 60, visitor(ip)
    spend = f"ask:usd:{day}"
    cmds = (_counter(f"ask:ip:{v}:h:{hour}", 3700) + _counter(f"ask:ip:{v}:d:{day}", 90000)
            + _counter(f"ask:all:m:{minute}", 120) + [["GET", spend]])
    res = store.pipeline(cmds)
    n_hour, n_day, n_min, spent = res[1], res[3], res[5], int(res[6] or 0)
    if n_hour > lim["per_ip_hour"] or n_day > lim["per_ip_day"]:
        return "visitor", ""
    if n_min > lim["per_minute"]:
        return "busy", ""
    reserve = int(worst_case_usd(lim) * 1e6)                    # micro-dollars
    if spent + reserve > lim["daily_usd"] * 1e6:
        return "budget", ""
    store.pipeline([["SET", spend, 0, "EX", 172800, "NX"], ["INCRBY", spend, reserve]])
    return None, spend


def settle(store, spend: str, lim: dict, actual_usd: float) -> None:
    store.pipeline([["INCRBY", spend, int(actual_usd * 1e6) - int(worst_case_usd(lim) * 1e6)]])


MESSAGES = {
    "off": "Questions are switched off on this copy of the site right now.",
    "visitor": "That is the limit of questions for now from this connection. Try again in an hour.",
    "busy": "A lot of people are asking right now. Try again in a minute.",
    "budget": "Today's budget for answering questions is spent. Try again tomorrow, or move the levers in Your 2050.",
    "store": "Questions are switched off right now (the usage counter could not be reached).",
}


def health() -> dict:
    lim = limits()
    ready = lim["enabled"] and bool(os.environ.get("ANTHROPIC_API_KEY")) and RestStore.from_env() is not None
    return {"ok": True, "hosted": True, "run": False, "ask": ready}


def _shape(a) -> dict:
    run = ([r for r in a.runs if r] or a.runs or [{}])[-1]
    return {"body": a.body or a.text, "declined": a.declined, "error": a.error, "outside": a.outside,
            "sources": [{"markers": s["markers"], "grade": s["grade"], "grade_label": s["grade_label"], "line": s["line"]}
                        for s in a.sources],
            "basis": a.basis, "apply": dict(run), "unmapped": [], "stand_in": a.stand_in, "model": a.model}


def answer(question: str, ip: str, store=None, client=None) -> tuple[int, dict]:
    """(status, body). The same body shape as scripts/serve_2050.py's /api/ask, so ask.js reads either."""
    q = (question or "").strip()
    if not q:
        return 400, {"error": "bad_request", "message": "Type a question first."}
    if len(q) > MAX_QUESTION:
        return 400, {"error": "bad_request", "message": f"Keep the question under {MAX_QUESTION} characters."}
    lim = limits()
    if not lim["enabled"] or (client is None and not os.environ.get("ANTHROPIC_API_KEY")):
        return 503, {"error": "off", "message": MESSAGES["off"]}
    declined = rules.gate(q)                                    # free: no model call, so no limit spent
    if declined:
        text = rules.decline_text(declined.reason, declined.suggestion)
        return 200, {"body": text, "declined": True, "error": "", "outside": [], "sources": [], "basis": "",
                     "apply": {}, "unmapped": [], "stand_in": False, "model": ""}
    store = store if store is not None else RestStore.from_env()
    if store is None:
        return 503, {"error": "store", "message": MESSAGES["store"]}
    try:
        why, spend = admit(store, ip, lim)
    except Exception:
        return 503, {"error": "store", "message": MESSAGES["store"]}
    if why:
        return 429, {"error": why, "message": MESSAGES[why]}
    agent = PolicyAgent(client=client, model=lim["model"], effort=lim["effort"], max_tokens=lim["max_tokens"],
                        output_budget=lim["max_output"], max_turns=lim["max_turns"], cache=True,
                        fallbacks=not lim["model"].startswith("claude-haiku"))   # Haiku has no server-side fallback
    try:
        a = agent.ask(q)
    except Exception as e:
        settle_quietly(store, spend, lim, 0.0)
        return 502, {"error": "agent", "message": friendly(e)}
    usd = cost_usd(lim["model"], a.input_tokens, a.output_tokens, a.cache_read_tokens, a.cache_write_tokens)
    settle_quietly(store, spend, lim, usd)
    print(json.dumps({"ask": True, "model": a.model, "turns": a.turns, "in": a.input_tokens, "out": a.output_tokens,
                      "cache_read": a.cache_read_tokens, "cache_write": a.cache_write_tokens, "usd": round(usd, 5),
                      "declined": a.declined, "error": a.error}))           # usage only: no question text, no IP
    return 200, _shape(a)


def settle_quietly(store, spend, lim, usd) -> None:
    try:
        settle(store, spend, lim, usd)
    except Exception:
        pass            # the reserve stays counted, which errs toward stopping early


def friendly(e: Exception) -> str:
    """A plain sentence for a failure of the model service. Never the exception text (it can carry request details)."""
    n = type(e).__name__
    if "RateLimit" in n or "Overloaded" in n or "InternalServer" in n:
        return "The model service is busy right now. Try again in a minute."
    if "Timeout" in n or "Connection" in n:
        return "The model service could not be reached. Try again in a minute."
    return "Something went wrong while answering. Try again in a minute."
