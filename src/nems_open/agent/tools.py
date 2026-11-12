"""The model's interface for the agent: five tools it can call, and the record of what they returned.

Every number the agent may state comes from one of these results. Each result is stored with an id (`r1`, `r2`...),
its numbers by name, and the citation (module, variable, grade) for each. `rules.py` turns the agent's final answer
into text using only those stored numbers, so a number it did not get from a tool cannot appear.

Tools: list_levers, run_scenario, read_result, trace_number, read_uncertainty. The agent ends by calling
submit_answer (defined in rules.py).
"""

from nems_open.agent import knowledge as K
from nems_open.agent import scenarios as S
from nems_open.agent import emulator as E

MAX_SCENARIOS = 8          # instant, but a question that needs more than this is a different question
MEASURE_KEYS = sorted(K.MEASURES)

EIA_REFERENCE = {"module": "EIA's AEO2026 reference run (cb2026)", "variable": "EIA's published run, not a model output",
                 "grade": "reference", "grade_label": "EIA's own number"}
UNCERTAIN = {"co2": ("US energy CO2", "", " million t"), "bill": ("Household energy bill", "$", " a year"),
             "gas": ("Home gas price", "$", "/MMBtu")}
LEVER_PROPS = {k: {"anyOf": [{"type": "number"}, {"type": "null"}]} for k in E.LEVERS}
SETTING = {"module": "Policy levers (run_model.Policy)", "variable": "a setting or limit of the model, not an output",
           "grade": "setting", "grade_label": "model setting"}


def module_names(desc: dict) -> str:
    """The module names behind a measure, each once, in order (four sectors share one stub name)."""
    return ", ".join(dict.fromkeys(p["name"] for p in desc["modules"]))


def _tool(name, description, properties, required=None):
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": properties, "required": required or list(properties),
                             "additionalProperties": False}}


SCHEMAS = [
    _tool("list_levers",
          "List the policy levers the model has, their ranges and units, the years and region level it reports, "
          "and the measures you can read. Call this first for questions about what can be changed.",
          {}),
    _tool("run_scenario",
          "Run the model with a set of levers and get a scenario id to read results from (instant). Every lever is a "
          "number or null; null means EIA's setting. Policy applies from 2027. " +
          " ".join(f"{k}: {v[2]} ({v[0]:g} to {v[1]:g}; null = {v[3]})." for k, v in E.LEVERS.items()) +
          " Building codes and appliance standards are not available here. Set only the levers the question is about.",
          LEVER_PROPS),
    _tool("read_result",
          "Read one measure for one year (2025 to 2050, US total) from a scenario, with EIA's reference value and the "
          "difference. Returns a result id to cite and the fields you can quote: value, reference, difference, "
          "difference_pct. The difference fields print as sizes without a sign: say lower or higher yourself from "
          "`direction`.",
          {"scenario_id": {"type": "string"},
           "measure": {"type": "string", "enum": MEASURE_KEYS},
           "year": {"type": "integer"}}),
    _tool("trace_number",
          "Trace a measure to the modules and variable behind it, each module's grade (matches EIA / our own model / "
          "fitted stand-in), and how far the demo's run is from EIA's reference. Use for 'where does this come from' "
          "and 'how far can I trust it'. Returns a result id.",
          {"measure": {"type": "string", "enum": MEASURE_KEYS}}),
    _tool("read_uncertainty",
          "Bands from our sampling of EIA's own side cases (10th, 50th and 90th percentile) for US energy CO2, "
          "household energy bill or home gas price, at a carbon price of 0, 50 or 100 dollars a ton, for a year. "
          "These are our sampling on stand-ins, not EIA's.",
          {"measure": {"type": "string", "enum": ["co2", "bill", "gas"]},
           "carbon_price": {"type": "integer"},
           "year": {"type": "integer"}}),
]


class Toolbox:
    """Executes tool calls and remembers every result for citation."""

    def __init__(self):
        self.results: dict[str, dict] = {}
        self.scenarios: dict[str, dict] = {}
        self.runs = []            # lever settings (page names) of each scenario this question ran

    # ---- bookkeeping ----
    def _store(self, tool: str, numbers: dict, citations: dict, **extra) -> str:
        rid = f"r{len(self.results) + 1}"
        self.results[rid] = {"tool": tool, "numbers": numbers, "citations": citations, **extra}
        return rid

    def citation(self, rid: str, field: str) -> dict:
        return self.results[rid]["citations"].get(field) or self.results[rid]["citations"]["*"]

    def lever_numbers(self) -> set[float]:
        """Lever values of the scenarios this question ran: the user's own inputs, allowed in the prose (also as percents)."""
        out = set()
        for r in self.runs:
            for v in r.values():
                out |= {float(v), round(float(v) * 100, 6)}
        return out

    # ---- dispatch ----
    def call(self, name: str, args: dict) -> tuple[dict, bool]:
        """(result, is_error)."""
        fn = getattr(self, f"_{name}", None)
        if fn is None:
            return {"error": f"unknown tool {name}"}, True
        try:
            return fn(**args), False
        except (KeyError, ValueError, TypeError) as e:
            return {"error": str(e)}, True

    # ---- the tools ----
    def _list_levers(self):
        numbers, cites = {}, {"*": SETTING}
        levers = {k: {"unit": v[2], "min": v[0], "max": v[1], "default": v[3]} for k, v in E.LEVERS.items()}
        for k, v in levers.items():
            for f in ("min", "max"):
                numbers[f"{k}.{f}"] = float(v[f])
        rid = self._store("list_levers", numbers, cites)
        return {"result_id": rid, "levers": levers,
                "reported": {"years": f"{K.YEARS[0]} to {K.YEARS[-1]}", "region": "US total",
                             "policy_starts": K.POLICY_START},
                "measures": {k: {"label": m.label, "unit": m.unit} for k, m in K.MEASURES.items()},
                "not_available": ["state, county or site level results", "hourly or daily results",
                                  "years before 2025 (history is EIA's data, not this model's)",
                                  "building codes and appliance standards (they need a 12-minute run with EIA's ported "
                                  "buildings code, which the page offers but this agent does not run)",
                                  "any lever not listed above"]}

    def _run_scenario(self, **levers):
        clean = E.check(levers)              # ValueError names what to fix
        if len(self.scenarios) >= MAX_SCENARIOS:
            raise ValueError(f"at most {MAX_SCENARIOS} scenarios per question; read what you have")
        sid, record = S.run(clean)
        self.scenarios[sid] = record
        if clean not in self.runs:
            self.runs.append(clean)
        out = {"scenario_id": sid, "levers": clean or "EIA's reference settings"}
        if clean.get("carbon_price", 0) > 100:
            out["warning"] = "a carbon price above 100 dollars a ton is outside the range the stand-ins were fitted on"
        return out

    def _read_result(self, scenario_id, measure, year):
        if scenario_id not in self.scenarios:
            raise KeyError(f"no scenario {scenario_id}; call run_scenario first")
        m = K.MEASURES[measure]
        v = S.value(self.scenarios[scenario_id], m, int(year))
        ref = S.reference_value(m, int(year))
        d = v - ref
        numbers = {"value": v, "reference": ref, "difference": abs(d),
                   "difference_pct": abs(d / ref * 100.0) if ref else 0.0}
        desc = K.describe(m)
        hist = int(year) < K.POLICY_START          # before policy starts the run is EIA's reference
        mod = {"module": module_names(desc), "variable": m.variable, "grade": desc["grade"],
               "grade_label": desc["grade_label"], "weakest_module": desc["weakest_module"],
               "what": f"{m.label}, {year}", "unit": m.unit, "measure": m.key}
        eia = {**EIA_REFERENCE, "what": f"{m.label}, {year}", "unit": m.unit, "measure": m.key}
        cites = {"*": eia if hist else mod, "reference": eia}
        fmt = {f: (m.prefix, m.suffix) for f in ("value", "reference", "difference")}
        fmt["difference_pct"] = ("", "%")
        rid = self._store("read_result", numbers, cites, digits=m.digits, fmt=fmt)
        direction = "same" if abs(d) < 0.5 * 10 ** -m.digits else ("higher" if d > 0 else "lower")
        out = {"result_id": rid, "measure": measure, "label": m.label, "unit": m.unit, "year": int(year),
               "scenario_id": scenario_id,
               "fields": {"value": round(v, 4), "reference": round(ref, 4), "difference": round(abs(d), 4),
                          "difference_pct": round(numbers["difference_pct"], 4)},
               "direction": f"the scenario is {direction} than EIA's reference" if direction != "same" else "the same as EIA's reference",
               "grade": "EIA's own number" if hist else desc["grade_label"], "weakest_module": desc["weakest_module"]}
        if m.note:
            out["note"] = m.note
        if hist:
            out["note"] = f"policy applies from {K.POLICY_START}; {year} is EIA's reference run, graded as EIA's own number"
        return out

    def _trace_number(self, measure):
        m = K.MEASURES[measure]
        desc = K.describe(m)
        numbers = {"gap_vs_eia_pct": desc["gap_vs_eia_pct"]} if desc["gap_vs_eia_pct"] is not None else {}
        cites = {"*": {"module": module_names(desc), "variable": m.variable,
                       "grade": desc["grade"], "grade_label": desc["grade_label"],
                       "weakest_module": desc["weakest_module"], "what": f"how {m.label} is produced", "unit": "%"}}
        rid = self._store("trace_number", numbers, cites, digits=2, fmt={"gap_vs_eia_pct": ("", "%")})
        return {"result_id": rid, **desc,
                "note": "the gap is for a no-policy run of the stand-ins against EIA's reference; with no policy the "
                        "stand-ins reproduce EIA's numbers by construction, and a policy moves them by fitted curves"}

    def _read_uncertainty(self, measure, carbon_price, year):
        u = K.uncertainty()
        entry = next((c for c in u["carbon"] if int(c["price"]) == int(carbon_price)), None)
        if entry is None:
            raise ValueError("carbon_price must be one of " + ", ".join(str(int(c["price"])) for c in u["carbon"]))
        if int(year) not in u["years"]:
            raise ValueError(f"year must be {u['years'][0]} to {u['years'][-1]}")
        i = u["years"].index(int(year))
        b = entry["bands"][measure]
        numbers = {"p10": b["p10"][i], "p50": b["p50"][i], "p90": b["p90"][i], "runs": float(entry["n"])}
        cites = {"*": {"module": "Uncertainty sampling over EIA's side cases on the stand-ins",
                       "variable": f"{measure} (nems_open.uncertainty)", "grade": "stand", "grade_label": "stand-in",
                       "weakest_module": "Fitted stand-ins",
                       "what": f"{UNCERTAIN[measure][0]} band, {year}, carbon price {int(carbon_price)}", "unit": u["units"][measure]}}
        digits = 0 if measure == "co2" else (0 if measure == "bill" else 2)
        _, pre, suf = UNCERTAIN[measure]
        rid = self._store("read_uncertainty", numbers, cites, digits=digits,
                          fmt={f: (pre, suf) for f in ("p10", "p50", "p90")})
        return {"result_id": rid, "measure": measure, "unit": u["units"][measure], "year": int(year),
                "carbon_price": int(carbon_price), "fields": numbers,
                "inputs": {k: f["label"] for k, f in u["factors"].items()},
                "label": "our sampling of EIA's own side cases on stand-ins, not EIA's"}
