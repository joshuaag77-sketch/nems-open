"""Switch archaeology, step 2: write web/data/switches.json and switches.js.

Joins what a script can establish (switch_sites.py: values, side cases, read sites) with what
readers established from the code (scripts/switches_meanings.json, one entry per key they read).
File keys nobody read get a description from their scedes row, and "unknown" where it says nothing.
Evidence lines in the meanings are checked against the source; a meaning whose evidence does
not exist is flagged, not dropped.

    python scripts/build_switches.py
"""

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

import switch_sites

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nems_open.paths import UPSTREAM  # noqa: E402
MEANINGS = ROOT / "scripts" / "switches_meanings.json"
WEB = ROOT / "web" / "data"
KINDS = {"policy", "technology_or_market_assumption", "model_control", "debug_reporting", "file_path",
         "build_or_software", "unknown"}
STATUS = {"active", "read_no_effect", "not_read", "unknown"}
SITE_CAP = 12
VERIFIED, ONE_READ, SCRIPT = "verified, second read", "unverified, one read", "unverified, script only"
CASES = {"altelec": "Alternative electricity", "alttrnp": "Alternative transportation",
         "electrnp": "Alternative electricity and transportation", "higheldmd": "High electricity demand",
         "highogs": "High oil and gas supply", "lowogs": "Low oil and gas supply",
         "highztc": "High zero-carbon technology cost", "lowztc": "Low zero-carbon technology cost",
         "hm2026": "High economic growth", "lm2026": "Low economic growth"}


def basename(v):
    return os.path.basename((v or "").replace(chr(92), "/"))


def path_only(x, value):
    """A file key whose side-case value differs only in folder: the same file name."""
    return x["filelist"] and x["value"] and value and basename(value).lower() == basename(x["value"]).lower()


def from_scedes(x):
    """A file key no reader looked at: only what its scedes row and the site search show."""
    name, source = basename(x["value"]), x["value"] or ""
    direction = x["filelist_format"].split(" ")[0].lower() if x["filelist_format"] else ""
    verb = {"read": "reads", "write": "writes"}.get(direction, "opens")
    who = x["owner_name"] or "NEMS"
    what = f"Names the file {name or 'unknown'} that {who} {verb}."
    what += f" Scedes description: {x['description']}." if x["description"] else " What it holds: unknown."
    is_source = "/source/" in source.replace(chr(92), "/") and source.lower().endswith((".f", ".f90", ".obj", ".o"))
    opened = [s for s in x["sites"] if s["kind"] in ("fortran_file_open", "python_scedes")]
    return {"what": what, "values": [], "allowed": "A file path", "modules": [x["owner_name"]] if x["owner_name"] else ["unknown"],
            "kind": "build_or_software" if is_source else "file_path", "status": "active" if opened else "unknown",
            "evidence": [f"{s['file']}:{s['line']}" for s in opened[:3]], "notes": "", "established_by": "script",
            "second_read": False, "correction": ""}


def evidence_ok(ref):
    path, _, line = ref.rpartition(":")
    p = UPSTREAM / path
    if not p.is_file() or not line.isdigit():
        return False
    with open(p, encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f) >= int(line) >= 1


def clean(m, key):
    out = {"what": m.get("what") or "unknown", "values": m.get("values") or [], "allowed": m.get("allowed") or "unknown",
           "modules": m.get("modules") or ["unknown"], "kind": m.get("kind"), "status": m.get("status"),
           "evidence": m.get("evidence") or [], "notes": m.get("notes") or "", "established_by": "reader",
           "second_read": bool(m.get("second_read")), "correction": m.get("correction") or ""}
    if out["kind"] not in KINDS:
        out["kind"] = "unknown"
    if out["status"] not in STATUS:
        out["status"] = "unknown"
    return out


def build():
    tmp = Path(tempfile.gettempdir()) / "switch_sites.json"
    switch_sites.main(tmp)
    facts = json.loads(tmp.read_text(encoding="utf-8"))
    meanings = {m["key"]: m for m in json.loads(MEANINGS.read_text(encoding="utf-8"))}
    rows, unread = [], []
    for x in facts:
        k = x["key"]
        real = {c: v for c, v in x["side_cases"].items() if not path_only(x, v)}
        if k in meanings:
            m = clean(meanings[k], k)
        elif x["filelist"] and not x["moreopt"] and not real:
            m = from_scedes(x)
        else:
            unread.append(k)
            m = {"what": "unknown", "values": [], "allowed": "unknown", "modules": ["unknown"], "kind": "unknown",
                 "status": "unknown", "evidence": [], "notes": "", "established_by": "none", "second_read": False, "correction": ""}
        bad = [e for e in m["evidence"] if not evidence_ok(e)]
        defaults = sorted({s["default"] for s in x["sites"] if s.get("default")})
        verification = VERIFIED if m["second_read"] else ONE_READ if m["established_by"] == "reader" else SCRIPT
        rows.append({
            "key": k, "verification": verification, "in_cb2026": x["in_cb2026"], "value": x["value"], "code_default": defaults,
            "owner": x["owner"], "owner_name": x["owner_name"], "section": x["section"], "description": x["description"],
            **m, "bad_evidence": bad,
            "side_cases": real, "side_cases_path_only": sorted(c for c in x["side_cases"] if c not in real),
            "other_scedes": x["other_scedes"], "moreopt": x["moreopt"], "filelist": x["filelist"],
            "sites": [{a: s.get(a) for a in ("file", "line", "kind", "routine", "text")} for s in x["sites"][:SITE_CAP]],
            "site_count": len(x["sites"]), "mention_count": x["mention_count"]})
    rows.sort(key=lambda r: r["key"].lower())
    summary = {
        "keys": len(rows), "in_cb2026": sum(r["in_cb2026"] for r in rows),
        "what_unknown": sum(r["what"] == "unknown" for r in rows),
        "by_status": dict(Counter(r["status"] for r in rows)), "by_kind": dict(Counter(r["kind"] for r in rows)),
        "established_by": dict(Counter(r["established_by"] for r in rows)),
        "verification": {v: sum(r["verification"] == v for r in rows) for v in (VERIFIED, ONE_READ, SCRIPT)},
        "second_read": sum(r["second_read"] for r in rows), "corrected": sum(bool(r["correction"]) for r in rows),
        "changed_in_side_cases": sum(bool(r["side_cases"]) for r in rows),
        "bad_evidence": sum(bool(r["bad_evidence"]) for r in rows)}
    summary["trust_note"] = (f"A separate reader tried to break {summary['second_read']} entries and changed {summary['corrected']}. "
                             "Treat anything unverified as a lead to check in the code, not as a finding.")
    doc = {"source": "EIA NEMS scedes files and source code, read in nems-upstream", "side_cases": CASES,
           "other_scedes": {"cb2026_solo": "cb2026 standalone variant", "prepett": "EMM transmission preprocessor run", "prepplt": "EMM plant preprocessor run"},
           "summary": summary, "switches": rows}
    WEB.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    (WEB / "switches.json").write_text(text, encoding="utf-8")
    (WEB / "switches.js").write_text("window.SWITCHES = " + json.dumps(doc, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    if unread:
        print("no reader and not a plain file key:", unread)
    for r in rows:
        if r["bad_evidence"]:
            print("bad evidence", r["key"], r["bad_evidence"])


if __name__ == "__main__":
    build()
