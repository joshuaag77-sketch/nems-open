"""The model's interface for the agent: five tools it can call, and the record of what they returned.

Every number the agent may state comes from one of these results. Each result is stored with an id (`r1`, `r2`...),
its numbers by name, and the citation (module, variable, grade) for each. `rules.py` turns the agent's final answer
into text using only those stored numbers, so a number it did not get from a tool cannot appear.

Tools: list_levers, run_scenario, read_result, trace_number, read_uncertainty. The agent ends by calling
submit_answer (defined in rules.py).
"""

from nems_open.agent import knowledge as K
from nems_open.agent import scenarios as S

MAX_LIVE_RUNS = 4          # a live run takes 4 to 8 seconds
MEASURE_KEYS = sorted(K.MEASURES)

EIA_REFERENCE = {"module": "EIA's AEO2026 reference run (cb2026)", "variable": "EIA's published run, not a model output",
                 "grade": "reference", "grade_label": "EIA's own number"}
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
          "Run the model with a set of levers (every sector on the fitted stand-ins, seconds a run) and get a "
          "scenario id to read results from. Policy applies from 2027. carbon_price: 2024 dollars per metric ton of "
          "CO2, 0 to 200 (above 100 is extrapolation). ev_share_2035: plug-in share of new light-duty sales in "
          "2035, 0 to 1, or null for EIA's reference path (about 65%). building_energy_2050: building fuel use "
          "in 2050 as a fraction of EIA's, 0.7 to 1.0. At most 4 live runs per question; the demo's grid "
          "(carbon 0 to 200 by 25, ev_share_2035 0.25, 0.8, 1.0 or null, building 1.0, 0.95, 0.9, 0.8) is instant.",
          {"carbon_price": {"type": "number"},
           "ev_share_2035": {"anyOf": [{"type": "number"}, {"type": "null"}]},
           "building_energy_2050": {"type": "number"}}),
    _tool("read_result",
          "Read one measure for one year (2025 to 2050, US total) from a scenario, with EIA's reference value and the "
          "difference. Returns a result id to cite and the fields you can quote: value, reference, difference, "
          "difference_pct.",
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
        self.runs = []            # lever settings of each scenario this question ran or loaded
        self.live_runs = 0

    # ---- bookkeeping ----
    def _store(self, tool: str, numbers: dict, citations: dict, **extra) -> str:
        rid = f"r{len(self.results) + 1}"
        self.results[rid] = {"tool": tool, "numbers": numbers, "citations": citations, **extra}
        return rid

    def citation(self, rid: str, field: str) -> dict:
        return self.results[rid]["citations"].get(field) or self.results[rid]["citations"]["*"]

    def lever_numbers(self) -> set[float]:
        """Lever values of the scenarios this question ran: the user's own inputs, allowed in the prose."""
        out = set()
        for r in self.runs:
            out |= {float(v) for v in r.values() if isinstance(v, (int, float))}
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
        levers = {
            "carbon_price": {"unit": "2024 dollars per metric ton CO2", "min": 0, "max": 200, "default": 0,
                             "note": "applies from 2027; above 100 is extrapolation of the fitted stand-ins"},
            "ev_share_2035": {"unit": "share of new light-duty sales that are plug-ins, 2035", "min": 0, "max": 1,
                              "default": "EIA's reference path (about 0.65)", "note": "ramps from 2027"},
            "building_energy_2050": {"unit": "building fuel use in 2050 as a fraction of EIA's", "min": 0.7, "max": 1.0,
                                     "default": 1.0, "note": "ramps from 2027; residential and commercial together"},
        }
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
                                  "commercial building code and efficiency standard levers (they need the slow "
                                  "ported commercial module, not run by this agent)",
                                  "any lever not listed above"]}

    def _run_scenario(self, carbon_price, ev_share_2035, building_energy_2050):
        problems = S.check_levers(carbon_price, ev_share_2035, building_energy_2050)
        if problems:
            raise ValueError("; ".join(problems))
        # on the grid it is a file read; off it, a live run (limited)
        sid_probe = S._script().scenario_id(
            int(carbon_price) if float(carbon_price).is_integer() else float(carbon_price),
            None if ev_share_2035 is None else round(float(ev_share_2035), 4), round(float(building_energy_2050), 4))
        on_grid = (S.WEB_DATA / "scenarios" / f"{sid_probe}.json").exists()
        if not on_grid and self.live_runs >= MAX_LIVE_RUNS:
            raise ValueError(f"at most {MAX_LIVE_RUNS} live runs per question; use grid settings or read what you have")
        sid, record, source = S.load(carbon_price, ev_share_2035, building_energy_2050)
        if source == "live run":
            self.live_runs += 1
        self.scenarios[sid] = record
        self.runs.append({"carbon_price": float(carbon_price), "building_energy_2050": float(building_energy_2050),
                          **({} if ev_share_2035 is None else {"ev_share_2035": float(ev_share_2035)})})
        out = {"scenario_id": sid, "source": source,
               "levers": {"carbon_price": carbon_price, "ev_share_2035": ev_share_2035,
                          "building_energy_2050": building_energy_2050}}
        if float(carbon_price) > S.CARBON_WARN:
            out["warning"] = "a carbon price above 100 dollars a ton is outside the range the stand-ins were fitted on"
        return out

    def _read_result(self, scenario_id, measure, year):
        if scenario_id not in self.scenarios:
            raise KeyError(f"no scenario {scenario_id}; call run_scenario first")
        m = K.MEASURES[measure]
        v = S.value(self.scenarios[scenario_id], m.path, int(year))
        ref = S.value(S.reference(), m.path, int(year))
        d = v - ref
        numbers = {"value": v, "reference": ref, "difference": d,
                   "difference_pct": (d / ref * 100.0) if ref else 0.0}
        desc = K.describe(m)
        cites = {"*": {"module": module_names(desc), "variable": m.variable,
                       "grade": desc["grade"], "grade_label": desc["grade_label"],
                       "weakest_module": desc["weakest_module"], "what": f"{m.label}, {year}, scenario {scenario_id}",
                       "unit": m.unit},
                 "reference": {**EIA_REFERENCE, "what": f"{m.label}, {year}", "unit": m.unit}}
        rid = self._store("read_result", numbers, cites, digits=m.digits)
        out = {"result_id": rid, "measure": measure, "label": m.label, "unit": m.unit, "year": int(year),
               "scenario_id": scenario_id, "fields": {k: round(x, 4) for k, x in numbers.items()},
               "grade": desc["grade_label"], "weakest_module": desc["weakest_module"]}
        if int(year) < K.POLICY_START:
            out["note"] = f"policy applies from {K.POLICY_START}; years before that match EIA's reference"
        return out

    def _trace_number(self, measure):
        m = K.MEASURES[measure]
        desc = K.describe(m)
        numbers = {"gap_vs_eia_pct": desc["gap_vs_eia_pct"]} if desc["gap_vs_eia_pct"] is not None else {}
        cites = {"*": {"module": module_names(desc), "variable": m.variable,
                       "grade": desc["grade"], "grade_label": desc["grade_label"],
                       "weakest_module": desc["weakest_module"], "what": f"how {m.label} is produced", "unit": "%"}}
        rid = self._store("trace_number", numbers, cites, digits=2)
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
                       "weakest_module": "Fitted stand-ins", "what": f"{u['units'][measure]}, {year}, "
                       f"carbon price {int(carbon_price)}", "unit": u["units"][measure]}}
        digits = 0 if measure == "co2" else (0 if measure == "bill" else 2)
        rid = self._store("read_uncertainty", numbers, cites, digits=digits)
        return {"result_id": rid, "measure": measure, "unit": u["units"][measure], "year": int(year),
                "carbon_price": int(carbon_price), "fields": numbers,
                "inputs": {k: f["label"] for k, f in u["factors"].items()},
                "label": "our sampling of EIA's own side cases on stand-ins, not EIA's"}
