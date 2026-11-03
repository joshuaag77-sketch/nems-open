"""The agent's rules, enforced in code. The prompt asks for these; this module makes them true.

1. Every number in an answer comes from a tool result and carries its module, variable and grade.
   The agent writes prose with placeholders ({c1}) and lists claims (result id and field). The code fills each
   placeholder with the stored number, adds a footnote with the module, variable and grade, and rejects a number
   written any other way. A number the agent was not given cannot appear.
2. If an answer rests on a stand-in (or on our own model, not a port), the code adds the statement that it does.
3. A question the model cannot resolve (a place below the national level, a site, a year outside 2025 to 2050,
   something that is not energy) is declined with the reason, before any model call when it is clear from the
   wording, and through submit_answer when the model sees it.
"""

import re
from dataclasses import dataclass, field

from nems_open.agent import knowledge as K

SCOPE = ("This model resolves the US as a whole in each year from 2025 to 2050, with three policy levers: a carbon "
         "price, the plug-in share of new car and truck sales, and building energy use. It does not resolve states, "
         "counties, neighbourhoods or sites, hours or days, years before 2025 (history is EIA's data), or anything "
         "outside US energy and CO2.")

SUBMIT = {"name": "submit_answer", "strict": True,
          "description": "End the turn with your answer. Put every number in the answer as a placeholder like {c1} and "
                         "list each as a claim naming the result id (r1, r2...) and the field to quote. Do not type "
                         "numbers yourself; the only ones allowed are years and numbers the user gave or you set in "
                         "run_scenario. If the model cannot resolve the question, set can_answer to false and give "
                         "the reason.",
          "input_schema": {"type": "object", "properties": {
              "can_answer": {"type": "boolean"},
              "answer": {"type": "string", "description": "prose with {c1} style placeholders for every number"},
              "claims": {"type": "array", "items": {"type": "object", "properties": {
                  "id": {"type": "string"}, "result_id": {"type": "string"}, "field": {"type": "string"},
                  "decimals": {"type": "integer"}}, "required": ["id", "result_id", "field", "decimals"],
                  "additionalProperties": False}},
              "reason_cannot_answer": {"type": "string"}},
              "required": ["can_answer", "answer", "claims", "reason_cannot_answer"], "additionalProperties": False}}


# ---- the scope gate ---------------------------------------------------------------------------------

STATES = ("alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho illinois "
          "indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi missouri "
          "montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont virginia washington "
          "wisconsin wyoming").split() + ["new hampshire", "new jersey", "new mexico", "new york", "north carolina",
                                          "north dakota", "rhode island", "south carolina", "south dakota", "west virginia"]
CITIES = ("pittsburgh philadelphia chicago houston dallas austin boston seattle portland denver phoenix atlanta miami "
          "detroit minneapolis baltimore brooklyn manhattan").split() + ["los angeles", "san francisco", "san diego",
                                                                         "new york city", "washington dc", "las vegas"]
GATES = [
    ("place", re.compile(r"\b(street|avenue|zip ?code|postal code|county|neighbou?rhood|hill|hilltop|ridge|"
                         r"my (town|city|village|farm|block|house|apartment|building)|our (town|city|village|farm))\b",
                         re.I),
     "it asks about a specific place or site, which is below the national level"),
    ("state_or_city", re.compile(r"\b(" + "|".join(STATES + CITIES) + r")\b", re.I),
     "it asks about a state or city; this agent reads national totals only"),
    ("hourly", re.compile(r"\b(hourly|each hour|per hour|by the hour|this (week|weekend|summer|winter)|tomorrow|today)\b", re.I),
     "it asks about hours, days or the near term; the model is annual"),
    ("not_energy", re.compile(r"\b(stock market|s&p|bitcoin|crypto|election|mortgage|recession odds|jobs? numbers?|"
                              r"unemployment|inflation rate|real estate prices?)\b", re.I),
     "it is outside US energy and CO2"),
]
YEAR_ASKED = re.compile(r"\b(?:in|by|for|during|at|as of)\s+(?:the year\s+)?(\d{4})\b", re.I)


@dataclass
class Declined:
    reason: str
    category: str


def gate(question: str) -> Declined | None:
    """A question that is clearly outside what the model can resolve, or None."""
    for category, pattern, reason in GATES:
        m = pattern.search(question)
        if m:
            return Declined(f"{reason} (\"{m.group(0)}\").", category)
    for m in YEAR_ASKED.finditer(question):
        year = int(m.group(1))
        if 1900 <= year < K.YEARS[0]:
            return Declined(f"it asks about {year}, before the model's first reported year {K.YEARS[0]}; "
                            "history is EIA's data, not this model's.", "year")
        if K.YEARS[-1] < year < 2200:
            return Declined(f"it asks about {year}, after the model's last year {K.YEARS[-1]}.", "year")
    return None


def decline_text(reason: str) -> str:
    return f"I can't answer that from this model: {reason}\n\n{SCOPE}"


# ---- checking and rendering an answer ---------------------------------------------------------------

PLACEHOLDER = re.compile(r"\{(c\d+)\}")
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th)?%?")
ORDINAL = re.compile(r"\d+(?:st|nd|rd|th)$")


@dataclass
class Claim:
    marker: int
    text: str
    citation: dict
    rid: str
    field: str


@dataclass
class Rendered:
    text: str
    claims: list[Claim] = field(default_factory=list)
    declined: bool = False
    stand_in: bool = False


def _fmt(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}"


def _stray_numbers(text: str, allowed: set) -> list[str]:
    """Numbers written in the text that are neither a placeholder, a year, nor something the user or a run supplied."""
    out = []
    for token in NUMBER.findall(PLACEHOLDER.sub("", text)):
        if ORDINAL.search(token):
            continue
        raw = token.rstrip("%").replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        if (re.fullmatch(r"(19|20)\d\d", raw) and 1990 <= v <= 2050) or v in allowed:
            continue
        out.append(f"the number {token} is written in the answer without a claim; put it in a claim or remove it")
    return out


def check(submission: dict, box, question: str) -> tuple[Rendered | None, list[str]]:
    """Validate a submit_answer input against the stored results. Returns (rendered, problems)."""
    problems = []
    can = submission.get("can_answer")
    prose = submission.get("answer", "")
    claims = submission.get("claims") or []
    allowed = set(box.lever_numbers())          # what the user said, and the lever values the agent ran
    for tok in NUMBER.findall(question):
        if not ORDINAL.search(tok):
            try:
                allowed.add(float(tok.rstrip("%").replace(",", "")))
            except ValueError:
                pass

    if can is False:
        if claims or PLACEHOLDER.search(prose):
            problems.append("a declined answer must not carry claims or numbers")
        problems += _stray_numbers(prose + " " + submission.get("reason_cannot_answer", ""), allowed)
        if not submission.get("reason_cannot_answer", "").strip():
            problems.append("reason_cannot_answer is required when can_answer is false")
        if problems:
            return None, problems
        text = decline_text(submission["reason_cannot_answer"].strip())
        return Rendered(text=text, declined=True), []

    by_id = {}
    for c in claims:
        cid = c.get("id")
        if cid in by_id:
            problems.append(f"claim id {cid} is repeated")
            continue
        by_id[cid] = c
        rid, f = c.get("result_id"), c.get("field")
        if rid not in box.results:
            problems.append(f"claim {cid}: no result {rid} (results this question: {', '.join(box.results) or 'none'})")
        elif f not in box.results[rid]["numbers"]:
            problems.append(f"claim {cid}: result {rid} has no field {f} (fields: {', '.join(box.results[rid]['numbers'])})")
        if not 0 <= int(c.get("decimals", 0)) <= 4:
            problems.append(f"claim {cid}: decimals must be 0 to 4")

    used = PLACEHOLDER.findall(prose)
    for cid in set(used) - set(by_id):
        problems.append(f"the answer uses {{{cid}}} but there is no claim {cid}")
    for cid in set(by_id) - set(used):
        problems.append(f"claim {cid} is never used in the answer")

    problems += _stray_numbers(prose, allowed)
    if problems:
        return None, problems

    order, markers = [], {}
    for cid in used:
        if cid not in markers:
            c = by_id[cid]
            markers[cid] = len(markers) + 1
            order.append(Claim(markers[cid], "", box.citation(c["result_id"], c["field"]), c["result_id"], c["field"]))

    def fill(m):
        cid = m.group(1)
        c = by_id[cid]
        res = box.results[c["result_id"]]
        value = res["numbers"][c["field"]]
        txt = _fmt(value, int(c.get("decimals", res.get("digits", 2))))
        if c["field"].endswith("_pct"):
            txt += "%"
        claim = order[markers[cid] - 1]
        claim.text = txt
        return f"{txt} [{markers[cid]}]"

    text = PLACEHOLDER.sub(fill, prose)
    text = text.replace("%%", "%")
    notes = [f"[{c.marker}] {c.citation['what'] if 'what' in c.citation else ''} = {c.text}. "
             f"Module: {c.citation['module']}. Variable: {c.citation['variable']}. Grade: {c.citation['grade_label']}."
             for c in order]
    stand = [c for c in order if c.citation["grade"] in ("stand", "within")]
    out = text.rstrip()
    if notes:
        out += "\n\nSources\n" + "\n".join(notes)
    if stand:
        modules = sorted({c.citation.get("weakest_module", c.citation["module"]) for c in stand})
        out += ("\n\nBasis: these numbers rest on stand-ins, not on EIA's own modules: " + "; ".join(modules) +
                ". With no policy the stand-ins reproduce EIA's reference run by construction; a policy moves them by "
                "curves fitted to EIA's side cases, so read policy effects as estimates, not as EIA's results.")
    return Rendered(text=out, claims=order, stand_in=bool(stand)), []
