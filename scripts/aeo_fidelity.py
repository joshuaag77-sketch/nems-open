"""AEO-style fidelity report: a finished run against EIA's AEO2026 reference (the cb2026 restart), table by table.

    python scripts/aeo_fidelity.py --run <path/to/reference.npz>          # one saved run
    python scripts/aeo_fidelity.py --latest <showroom folder>             # newest reference.npz in it or its old-* folders
    python scripts/aeo_fidelity.py --run <npz> --out docs/fidelity        # where the .md and .json go

Reads saved outputs only (a full_model.save_run archive and the cb2026 arrays). It solves nothing.

Each line is one AEO series, named the way EIA's tables name it, in EIA's units. For every report year it
gives our value, EIA's value and the percent difference, then a status for the line:

  PASS         every model year is inside the line's tolerance
  FLAG         at least one model year is outside it (the gap beats both the percent and the absolute floor)
  HELD         our value equals EIA's in every model year (to 1 part in a million): the run carried EIA's number,
               it did not compute it. Not a pass
  NOT IN RUN   the saved run has no array for this series; EIA's value is shown alone
  NO EIA VALUE an EIA array the line names was not found (should not happen with the cb2026 restart)

2025 is shown but not graded: the run starts in its first model year (the first year in the archive's
"stable" list, 2027 for the showroom runs), so 2025 is EIA's history in both columns.

EIA's values are read from the same restart arrays the model reads (QBLK, MPBLK, UEFDOUT, UDATOUT, EMISSION,
NGTDMREP, OGSMOUT, MACOUT). Every line names its arrays in the JSON ("source"), so a reviewer can trace it.
Prices are converted from NEMS's 1987 dollars with EIA's own GDP deflator (MACOUT/MC_JPGDP) to --dollar-year.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

Y0, US = 1990, 10
YEARS = (2025, 2030, 2035, 2040, 2050)
FIRST_MODEL_YEAR = 2027
CO2_PER_C = 44.0 / 12.0
MMBTU_PER_KWH = 0.003412
TBTU_PER_BCF = 1.037                 # dry gas heat content, the conversion EIA's tables use (about 1,037 Btu/cf)
NUM_R = 25                           # EMM regions; rows 26-28 of the UDATOUT/UEFDOUT arrays are totals

# Tolerance by kind of line: (percent, absolute floor in the line's own unit). A cell is outside tolerance only
# when it beats both, so a tiny line (coal in homes, a retired plant type) cannot fail on percent alone.
TOLERANCE = {
    "consumption": (3.0, 0.05),      # quads
    "gas_volume": (5.0, 0.10),       # trillion cubic feet
    "supply": (5.0, 0.10),           # Tcf, million barrels a day
    "generation": (5.0, 10.0),       # billion kWh
    "sales": (3.0, 20.0),            # billion kWh
    "capacity": (15.0, 2.0),         # GW, the bounds of emm/capacity_report.py
    "price": (5.0, 0.10),            # $/MMBtu, cents/kWh
    "co2": (3.0, 5.0),               # million metric tons
    "macro": (1.0, 0.0),             # billion chained 2017 $
}


class Missing(KeyError):
    """The saved run has no array for this series."""


# ---- the two sides ----------------------------------------------------------------------------------

# Generation: our dispatch groups and EIA's UEFDOUT/UGN<type>NR arrays (billion kWh), as full_model.GEN.
GEN = {
    "coal": (("coal", "coal_ccs"), ("clnr", "cfnr")),
    "gas": (("gas_cc", "gas_ccs", "gas_ct", "steam"), ("gfnr", "ginr", "gcnr")),
    "nuclear": (("nuclear",), ("urnr",)),
    "renewables": (("hydro", "wind", "solar", "other"), ("honr",)),
    "hydro": (("hydro",), ("hynr",)),
    "wind": (("wind",), ("wnnr", "wlnr", "wfnr")),
    "solar": (("solar",), ("sonr", "pvnr", "ptnr")),
}
# Capacity: our capacity-LP groups and EIA's UDATOUT/UCAP<prefix><u|n> arrays (GW), after emm/dispatch.py
# CAPACITY_PREFIXES. Our "coal" excludes CCS retrofits (dispatch.py takes coal_ccs out), EIA's cs includes them,
# so coal compares coal + coal_ccs. Our gas_conv (coal units converted to gas) sits in EIA's steam (prefix ng).
# A prefix "-xx" is subtracted. EIA's cc holds as (CCS), so combined cycle is cc + fc against all our CC groups.
CAP = {
    "coal": (("coal", "coal_ccs"), ("cs", "ig", "pq", "is", "oc")),
    "steam": (("steam", "gas_conv"), ("os", "ng")),
    "cc": (("gas_cc", "gas_cc_new", "gas_ccs"), ("cc", "fc")),
    "ct": (("gas_ct", "gas_ct_new"), ("ct", "ic", "i2")),
    "nuclear": (("nuclear",), ("nu", "sm")),
    "pumped": (("pumped",), ("ps", "p2")),
    "battery": (("battery",), ("ds", "dp", "db")),
    "hydro": (("hydro",), ("hy",)),
    "wind": (("wind",), ("wn", "wf", "wl")),
    "solar": (("solar",), ("pv", "pt", "st", "so", "ss", "s2")),
    "other": (("other",), ("ge", "wd", "ms", "bi", "gn", "ag", "ti", "hi", "ho")),
}
CO2_ARRAYS = {"rs": "emrsc", "cm": "emcmc", "in": "emincc", "tr": "emtrc", "el": "emelc"}
# Fuel CO2 (Table 18 by fuel): fuel use times EIA's carbon factors (EMEBLK, kg C per MMBtu), computed the same way
# for both sides. It counts combustion only (no feedstock carbon, no CCS), so it tests fuel use, not Table 18's
# printed petroleum total. Residual fuel is counted as its two grades (rl, rh), not their sum (rs).
FUEL_CO2 = {
    "petroleum": ("dsrs", "dscm", "dsin", "dstr", "dsel", "ksrs", "kscm", "ksin", "lgrs", "lgcm", "lgin", "lgtr",
                  "mgcm", "mgin", "mgtr", "jftr", "rlcm", "rlin", "rltr", "rlel", "rhtr", "rhel", "pcin", "pcel",
                  "otin", "ottr"),
    "gas": ("ngrs", "ngcm", "ngin", "ngtr", "ngel"),
    "coal": ("clrs", "clcm", "clin", "clel", "mcin"),
}
EL_FUELS = ("cl", "ng", "rs", "ds", "ur", "tr", "pc")   # power-plant fuels, as full_model.EL_FUELS


class Eia:
    """EIA's AEO2026 reference. `arrays`: restart arrays by name (full shapes), or None to read cb2026."""

    def __init__(self, arrays: dict | None = None):
        self._a = arrays if arrays is not None else _cb2026()

    def raw(self, name: str) -> np.ndarray:
        if name not in self._a:
            raise Missing(name)
        return np.asarray(self._a[name], dtype=np.float64)

    def q(self, name: str) -> np.ndarray:
        return self.raw(f"QBLK/{name}")[US]

    def p(self, name: str) -> np.ndarray:
        return self.raw(f"MPBLK/{name}")[US]

    def co2(self, s: str) -> np.ndarray:
        return self.raw(f"EMISSION/{CO2_ARRAYS[s]}")[US, 0] * CO2_PER_C

    def gen(self, key: str) -> np.ndarray:
        return sum(self.raw(f"UEFDOUT/ugn{n}")[:, :NUM_R].sum(axis=(0, 1)) for n in GEN[key][1])

    def cap(self, key: str) -> np.ndarray:
        total = np.zeros(61)
        for p in CAP[key][1]:
            sign = -1.0 if p.startswith("-") else 1.0
            for o in ("u", "n"):
                name = f"UDATOUT/ucap{p.lstrip('-')}{o}"
                if name in self._a:
                    total += sign * np.nan_to_num(self.raw(name)[:NUM_R]).sum(axis=0)
        return total

    def henry_hub(self):
        return self.raw("NGTDMREP/oghhprng")

    def dry_gas(self):
        return self.raw("OGSMOUT/ogqngrep")[8]            # Bcf; row 9 of OGQNGREP is the US total

    def gas_exports(self, kind: str):
        e = self.raw("NGTDMREP/ngexpvol")                 # Bcf: Canada, Mexico, LNG, total
        return e[2] if kind == "lng" else e[0] + e[1]

    def gas_imports(self):
        i = self.raw("NGTDMREP/ngimpvol")                 # Bcf: Canada, Mexico, LNG, total
        return i[0] + i[1]

    def crude(self):
        return self.raw("OGSMOUT/ogqcrrep")[5] / 365.0    # million barrels a year -> a day; row 6 is the total

    def brent(self):
        return self.raw("INTOUT/brent_price")

    def wti(self):
        return self.raw("INTOUT/wti_price")

    def gdp(self):
        return self.raw("MACOUT/mc_gdpr")

    def factor(self, name: str) -> np.ndarray:
        return self.raw(f"EMEBLK/e{name}")


class Run:
    """A saved run (full_model.save_run archive). `arrays`: archive arrays by name, or a path to the .npz.
    Totals the loop does not update (QTSEL, QTSAS) are rebuilt from NEMS's identity, as full_model.numbers does."""

    def __init__(self, arrays, eia: Eia):
        if isinstance(arrays, (str, Path)):
            with np.load(arrays, allow_pickle=False) as z:
                arrays = {k: z[k] for k in z.files}
        self._a, self.eia = arrays, eia
        st = arrays.get("stable")
        self.stable = {int(y): bool(s) for y, s in np.asarray(st).reshape(-1, 2) if y} if st is not None else {}
        self.first = min(self.stable) if self.stable else FIRST_MODEL_YEAR

    def _get(self, name: str) -> np.ndarray:
        if name not in self._a:
            raise Missing(name)
        return np.asarray(self._a[name], dtype=np.float64)

    def q(self, name: str) -> np.ndarray:
        if f"d:QBLK/{name}" in self._a:                   # rebuilt at save time (full_model.derived_totals)
            return self._get(f"d:QBLK/{name}")
        if name == "qtsel":
            base = self.eia.q("qtsel")
            return base + sum(self.q(f"q{f}el") - self.eia.q(f"q{f}el") for f in EL_FUELS if f"q:QBLK/q{f}el" in self._a)
        if name == "qtsas":
            return sum(self.q(f"qts{s}") for s in ("rs", "cm", "in", "tr", "el")) - self.q("qelas")
        return self._get(f"q:QBLK/{name}")[US]

    def p(self, name: str) -> np.ndarray:
        return self._get(f"p:MPBLK/{name}")[US]

    def co2(self, s: str) -> np.ndarray:
        return self._get(f"c:{s}")[US]

    def gen(self, key: str) -> np.ndarray:
        names = [f"g:{n}" for n in GEN[key][0]]
        if not any(n in self._a for n in names):
            raise Missing(names[0])
        return sum(self._get(n) for n in names if n in self._a)

    def cap(self, key: str) -> np.ndarray:
        names = [f"k:capacity:{n}" for n in CAP[key][0]]
        if not any(n in self._a for n in names):
            raise Missing(names[0])
        total = sum(self._get(n).sum(axis=1) for n in names if n in self._a)
        # Years the capacity LP did not solve hold zeros for every group: no value, not zero capacity.
        solved = sum(self._get(k).sum(axis=1) for k in self._a if k.startswith("k:capacity:")) > 0
        return np.where(solved, total, np.nan)

    def henry_hub(self):
        return self._get("n:henry_hub")

    def dry_gas(self):
        return self._get("n:production")                  # Bcf: NGMM's (ogs="aimms") or the gas-market stand-in's

    def gas_exports(self, kind: str):
        return self._get("n:exports_lng" if kind == "lng" else "n:exports_pipeline")   # Bcf, NGMM (ogs="aimms")

    def gas_imports(self):
        return self._get("n:imports_pipeline")

    def crude(self):
        return self._get("x:crude") / 365.0                # million barrels a year -> a day (HSM)

    def brent(self):
        return self._get("x:brent")                       # an input: HELD unless a lever moves it

    def wti(self):
        return self._get("x:wti")

    def gdp(self):
        return self._get("x:mc_gdpr")

    def factor(self, name: str) -> np.ndarray:
        return self.eia.factor(name)


def _cb2026() -> dict:
    """The cb2026 arrays: the cached blocks (supply_standin.data.load_case) plus the few restart arrays outside
    them, read one by one from the restart archive (np.load is lazy, so this stays small)."""
    from nems_open.supply_standin.data import load_case, restart_path
    a = dict(load_case("cb2026"))
    extra = ["NGTDMREP/oghhprng", "NGTDMREP/ngexpvol", "NGTDMREP/ngimpvol", "OGSMOUT/ogqngrep", "OGSMOUT/ogqcrrep"]
    with np.load(restart_path("cb2026"), allow_pickle=False) as z:
        extra += [k for k in z.files if k.startswith("UDATOUT/ucap")]
        for k in extra:
            if k not in a:
                a[k] = z[k]
    return a


# ---- the lines ----------------------------------------------------------------------------------------

def _q(*names, scale=1e-3):
    return lambda s: sum(s.q(n) for n in names) * scale


def _price(name, per=1.0):
    return lambda s, k: s.p(name) * k * per


def _fuel_co2(group):
    def f(s):
        return sum(s.q(f"q{n}") * s.factor(n) for n in FUEL_CO2[group]) / 1000.0 * CO2_PER_C
    return f


def _cents(name):
    return _price(name, MMBTU_PER_KWH * 100)


def _sum(*fns):
    return lambda s: sum(f(s) for f in fns)


# (table, EIA series name, unit, kind, value function, EIA arrays). A value function takes the source
# (Eia or Run) and, for prices, the 1987-to-report-year dollar factor.
T1, T2, T8, T9, T13, T15, T18, MAC, T3 = (
    "Table 1. Total energy supply, disposition, and price summary",
    "Table 2. Energy consumption by sector and source",
    "Table 8. Electricity supply, disposition, prices, and emissions",
    "Table 9. Electricity generating capacity",
    "Table 13. Natural gas supply, disposition, and prices",
    "Table 15. Coal supply, disposition, and prices",
    "Table 18. Energy-related carbon dioxide emissions by sector and source",
    "Macroeconomic indicators (Table 20)",
    "Table 3. Energy prices by sector and source (delivered prices)",
)
BCF_TO_TCF = 1e-3
TBTU_TO_TCF = 1e-3 / TBTU_PER_BCF


def lines() -> list[dict]:
    L = []

    def add(table, name, unit, kind, fn, source, price=False):
        L.append({"table": table, "series": name, "unit": unit, "kind": kind, "fn": fn, "source": source, "price": price})

    # Table 1
    add(T1, "Production: Crude oil and lease condensate", "million barrels per day", "supply", lambda s: s.crude(),
        "OGSMOUT/OGQCRREP(6)")
    add(T1, "Production: Dry natural gas", "trillion cubic feet", "supply", lambda s: s.dry_gas() * BCF_TO_TCF,
        "OGSMOUT/OGQNGREP(9)")
    for sec, nm in (("rs", "Residential"), ("cm", "Commercial"), ("in", "Industrial"), ("tr", "Transportation"),
                    ("el", "Electric power"), ("as", "Total")):
        add(T1, f"Consumption by sector: {nm}", "quads", "consumption", _q(f"qts{sec}"), f"QBLK/QTS{sec.upper()}")
    for f, nm in (("tp", "Petroleum and other liquids"), ("ng", "Natural gas"), ("cl", "Coal"), ("ur", "Nuclear"),
                  ("tr", "Renewable energy")):
        add(T1, f"Consumption by source: {nm}", "quads", "consumption",
            _q(f"qurel") if f == "ur" else _q(f"q{f}as"), "QBLK/QUREL" if f == "ur" else f"QBLK/Q{f.upper()}AS")
    add(T1, "Prices: Brent spot", "$/barrel", "price", lambda s, k: s.brent() * k, "INTOUT/BRENT_PRICE", True)
    add(T1, "Prices: West Texas Intermediate spot", "$/barrel", "price", lambda s, k: s.wti() * k,
        "INTOUT/WTI_PRICE", True)
    add(T1, "Prices: Natural gas at Henry Hub", "$/MMBtu", "price", lambda s, k: s.henry_hub() * k,
        "NGTDMREP/OGHHPRNG", True)
    add(T1, "Prices: Electricity, all sectors", "cents/kWh", "price", _cents("pelas"), "MPBLK/PELAS", True)

    # Table 2
    t2 = {
        "rs": ("Residential", (("Propane", "qlgrs"), ("Distillate fuel oil", "qdsrs"), ("Natural gas", "qngrs"),
                               ("Purchased electricity", "qelrs"), ("Delivered energy", "qtsrs"))),
        "cm": ("Commercial", (("Distillate fuel oil", "qdscm"), ("Natural gas", "qngcm"),
                              ("Purchased electricity", "qelcm"), ("Delivered energy", "qtscm"))),
        "in": ("Industrial", (("Petroleum and other liquids", "qtpin"), ("Natural gas", "qngin"),
                              ("Coal (steam and metallurgical)", ("qclin", "qmcin")), ("Renewable energy", "qtrin"),
                              ("Purchased electricity", "qelin"), ("Delivered energy", "qtsin"))),
        "tr": ("Transportation", (("Motor gasoline", "qmgtr"), ("Jet fuel", "qjftr"), ("Distillate fuel oil", "qdstr"),
                                  ("Natural gas", "qngtr"), ("Purchased electricity", "qeltr"),
                                  ("Delivered energy", "qtstr"))),
        "el": ("Electric power", (("Petroleum and other liquids", "qtpel"), ("Natural gas", "qngel"),
                                  ("Steam coal", "qclel"), ("Nuclear", "qurel"), ("Renewable energy", "qtrel"),
                                  ("Total", "qtsel"))),
    }
    for sec, (snm, rows) in t2.items():
        for nm, v in rows:
            names = v if isinstance(v, tuple) else (v,)
            add(T2, f"{snm}: {nm}", "quads", "consumption", _q(*names), " + ".join(f"QBLK/{n.upper()}" for n in names))
    add(T2, "Total: Total energy consumption", "quads", "consumption", _q("qtsas"), "QBLK/QTSAS")

    # Table 3 (delivered prices, the ones a reviewer checks first)
    for nm, v, cents in (("Residential: Electricity", "pelrs", True), ("Residential: Natural gas", "pngrs", False),
                         ("Residential: Propane", "plgrs", False), ("Residential: Distillate fuel oil", "pdsrs", False),
                         ("Commercial: Electricity", "pelcm", True), ("Commercial: Natural gas", "pngcm", False),
                         ("Industrial: Electricity", "pelin", True), ("Industrial: Natural gas", "pngin", False),
                         ("Industrial: Steam coal", "pclin", False),
                         ("Transportation: Motor gasoline", "pmgtr", False), ("Transportation: Jet fuel", "pjftr", False),
                         ("Transportation: Diesel fuel (distillate)", "pdstr", False),
                         ("Electric power: Natural gas", "pngel", False), ("Electric power: Steam coal", "pclel", False)):
        add(T3, nm, "cents/kWh" if cents else "$/MMBtu", "price", _cents(v) if cents else _price(v), f"MPBLK/{v.upper()}",
            True)

    # Table 8
    for key, nm in (("coal", "Coal"), ("gas", "Natural gas"), ("nuclear", "Nuclear power"),
                    ("renewables", "Renewable sources"), ("hydro", "Conventional hydroelectric power (in renewables)"),
                    ("wind", "Wind (in renewables)"), ("solar", "Solar (in renewables)")):
        add(T8, f"Generation by fuel: {nm}", "billion kWh", "generation", (lambda k: lambda s: s.gen(k))(key),
            " + ".join(f"UEFDOUT/UGN{n.upper()}" for n in GEN[key][1]))
    add(T8, "Generation: Coal, natural gas, nuclear and renewables together", "billion kWh", "generation",
        _sum(*[(lambda k: lambda s: s.gen(k))(k) for k in ("coal", "gas", "nuclear", "renewables")]),
        "sum of the four lines above")
    add(T8, "Electricity sales", "billion kWh", "sales", lambda s: s.q("qelas") / 3.412, "QBLK/QELAS")
    for nm, v in (("Residential", "pelrs"), ("Commercial", "pelcm"), ("Industrial", "pelin"),
                  ("Transportation", "peltr"), ("All sectors average", "pelas")):
        add(T8, f"End-use prices: {nm}", "cents/kWh", "price", _cents(v), f"MPBLK/{v.upper()}", True)
    add(T8, "Emissions from the electric power sector: Carbon dioxide", "million metric tons", "co2",
        lambda s: s.co2("el"), "EMISSION/EMELC(11,1) x 44/12")

    # Table 9
    for key, nm in (("coal", "Coal"), ("steam", "Oil and natural gas steam"), ("cc", "Combined cycle"),
                    ("ct", "Combustion turbine/diesel"), ("nuclear", "Nuclear"), ("pumped", "Pumped storage"),
                    ("battery", "Diurnal storage"), ("hydro", "Conventional hydroelectric power"), ("wind", "Wind"),
                    ("solar", "Solar"), ("other", "Other renewable and other")):
        add(T9, f"Electric power sector capacity: {nm}", "gigawatts", "capacity", (lambda k: lambda s: s.cap(k))(key),
            " + ".join(f"UDATOUT/UCAP{p.upper()}U,N" for p in CAP[key][1]))
    add(T9, "Electric power sector capacity: Total", "gigawatts", "capacity",
        _sum(*[(lambda k: lambda s: s.cap(k))(k) for k in CAP]), "sum of the lines above")

    # Table 13
    add(T13, "Dry gas production", "trillion cubic feet", "gas_volume", lambda s: s.dry_gas() * BCF_TO_TCF,
        "OGSMOUT/OGQNGREP(9)")
    add(T13, "Pipeline imports", "trillion cubic feet", "gas_volume", lambda s: s.gas_imports() * BCF_TO_TCF,
        "NGTDMREP/NGIMPVOL(1)+(2)")
    add(T13, "Pipeline exports", "trillion cubic feet", "gas_volume", lambda s: s.gas_exports("pipe") * BCF_TO_TCF,
        "NGTDMREP/NGEXPVOL(1)+(2)")
    add(T13, "Liquefied natural gas exports", "trillion cubic feet", "gas_volume",
        lambda s: s.gas_exports("lng") * BCF_TO_TCF, "NGTDMREP/NGEXPVOL(3)")
    for nm, v in (("Residential", "qngrs"), ("Commercial", "qngcm"), ("Industrial", "qngin"),
                  ("Electric power", "qngel"), ("Transportation", "qngtr"), ("Total", "qngas")):
        add(T13, f"Consumption by sector: {nm}", "trillion cubic feet", "gas_volume", _q(v, scale=TBTU_TO_TCF),
            f"QBLK/{v.upper()} / 1.037")
    add(T13, "Henry Hub spot price", "$/MMBtu", "price", lambda s, k: s.henry_hub() * k, "NGTDMREP/OGHHPRNG", True)
    for nm, v in (("Residential", "pngrs"), ("Commercial", "pngcm"), ("Industrial", "pngin"),
                  ("Electric power", "pngel")):
        add(T13, f"Delivered prices: {nm}", "$/MMBtu", "price", _price(v), f"MPBLK/{v.upper()}", True)

    # Table 15 (quantities in quads: the run keeps Btu, not short tons)
    for nm, v in (("Commercial and institutional", ("qclcm",)), ("Coke plants (metallurgical coal)", ("qmcin",)),
                  ("Other industrial", ("qclin",)), ("Electric power", ("qclel",)), ("Total coal consumption", ("qclas",))):
        add(T15, f"Consumption by sector: {nm}", "quads", "consumption", _q(*v), " + ".join(f"QBLK/{n.upper()}" for n in v))
    add(T15, "Delivered prices: Electric power", "$/MMBtu", "price", _price("pclel"), "MPBLK/PCLEL", True)
    add(T15, "Delivered prices: Industrial (steam coal)", "$/MMBtu", "price", _price("pclin"), "MPBLK/PCLIN", True)

    # Table 18
    for sec, nm in (("rs", "Residential"), ("cm", "Commercial"), ("in", "Industrial"), ("tr", "Transportation"),
                    ("el", "Electric power")):
        add(T18, f"By sector: {nm}", "million metric tons", "co2", (lambda x: lambda s: s.co2(x))(sec),
            f"EMISSION/{CO2_ARRAYS[sec].upper()}(11,1) x 44/12")
    add(T18, "By sector: Total carbon dioxide", "million metric tons", "co2",
        lambda s: sum(s.co2(x) for x in CO2_ARRAYS), "sum of the five sectors")
    for g, nm in (("petroleum", "Petroleum and other liquids"), ("gas", "Natural gas"), ("coal", "Coal")):
        add(T18, f"By fuel: {nm} (combustion, fuel use x EIA carbon factors)", "million metric tons", "co2",
            _fuel_co2(g), "QBLK fuel use x EMEBLK factors x 44/12")

    # Macro
    add(MAC, "Real gross domestic product", "billion chained 2017 dollars", "macro", lambda s: s.gdp(),
        "MACOUT/MC_GDPR")
    return L


# ---- comparing ------------------------------------------------------------------------------------------

def dollar_factor(eia: Eia, year: int) -> float:
    d = eia.raw("MACOUT/mc_jpgdp")                     # index 0 is 1987
    return float(d[year - 1987] / d[0])


def _value(line, src, k):
    try:
        v = line["fn"](src, k) if line["price"] else line["fn"](src)
    except Missing:
        return None
    return np.asarray(v, dtype=np.float64)


def compare(run: Run, eia: Eia, years=YEARS, dollar_year: int = 2025) -> dict:
    k = dollar_factor(eia, dollar_year)
    out = []
    for line in lines():
        e, m = _value(line, eia, k), _value(line, run, k)
        pct, floor = TOLERANCE[line["kind"]]
        cells = {}
        for y in years:
            j = y - Y0
            ev = None if e is None or not np.isfinite(e[j]) else float(e[j])
            mv = None if m is None or not np.isfinite(m[j]) else float(m[j])
            c = {"ours": mv, "eia": ev, "diff_pct": None, "graded": y >= run.first, "ok": None, "times_tol": None,
                 "converged": run.stable.get(y, True)}
            if mv is not None and ev is not None:
                c["diff_pct"] = 100.0 * (mv / ev - 1.0) if ev else (0.0 if mv == 0 else None)
                # The gap over what the line allows: the larger of the floor and the percent of EIA's value.
                allowed = max(floor, pct / 100.0 * abs(ev))
                c["times_tol"] = abs(mv - ev) / allowed if allowed else (0.0 if mv == ev else float("inf"))
                c["ok"] = c["times_tol"] <= 1.0
            cells[y] = c
        model = [c for c in cells.values() if c["graded"] and c["ours"] is not None and c["eia"] is not None]
        if e is None:
            status = "NO EIA VALUE"           # an EIA array this line names is not in the arrays read: a wiring error
        elif m is None:
            status = "NOT IN RUN"
        elif not model:
            status = "NO MODEL YEARS"
        elif all(abs(c["ours"] - c["eia"]) <= 1e-6 * max(1.0, abs(c["eia"])) for c in model):
            status = "HELD"
        else:
            status = "PASS" if all(c["ok"] for c in model) else "FLAG"
        worst = None
        graded = [(y, c) for y, c in cells.items() if any(c is x for x in model)]
        if graded and status in ("PASS", "FLAG"):
            y, c = max(graded, key=lambda t: t[1]["times_tol"])
            worst = {"year": y, "diff_pct": c["diff_pct"], "times_tol": c["times_tol"]}
        out.append({"table": line["table"], "series": line["series"], "unit": line["unit"], "kind": line["kind"],
                    "tolerance_pct": pct, "tolerance_floor": floor, "source": line["source"], "status": status,
                    "worst": worst, "years": cells})
    return {"lines": out, "dollar_year": dollar_year, "first_model_year": run.first,
            "not_converged": sorted(y for y, s in run.stable.items() if not s)}


def worst(result: dict, n: int = 15) -> list[dict]:
    """The n lines furthest from EIA, by their worst gap in multiples of the line's tolerance. A series that
    appears in two tables (Henry Hub in Tables 1 and 13) is listed once, under its first table."""
    rows = sorted((r for r in result["lines"] if r["status"] in ("PASS", "FLAG") and r["worst"]),
                  key=lambda r: -r["worst"]["times_tol"])
    out, seen = [], set()
    for r in rows:
        first = r["source"].split(" ")[0]            # the restart array, without a unit conversion after it
        key = first if "/" in first else (r["table"], r["series"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out[:n]


# ---- writing --------------------------------------------------------------------------------------------

def _fmt(v):
    if v is None:
        return "n/a"
    a = abs(v)
    return f"{v:,.0f}" if a >= 1000 else f"{v:,.1f}" if a >= 100 else f"{v:,.2f}" if a >= 1 else f"{v:,.3f}"


def _pct(d):
    return "n/a" if d is None else f"{d:+.1f}%"


def _cell(c):
    if c["eia"] is None and c["ours"] is None:
        return "n/a"
    if c["ours"] is None:
        return f"- / {_fmt(c['eia'])}"
    d = "" if c["diff_pct"] is None else f" ({c['diff_pct']:+.1f}%)"
    mark = "" if not c["graded"] or c["ok"] is None or c["ok"] else " !"
    nc = "" if c["converged"] else " nc"
    return f"{_fmt(c['ours'])} / {_fmt(c['eia'])}{d}{mark}{nc}"


def run_status(path: Path) -> dict:
    """The showroom's status.json entry for this run (which LFMM it used, when it finished, any logged error)."""
    f = path.parent / "status.json"
    try:
        st = json.loads(f.read_text()).get(path.stem, {})
    except (OSError, ValueError):
        return {}
    return {"lfmm": st.get("lfmm"), "started": st.get("started"), "finished": st.get("finished"),
            "error": st.get("error"), "traceback_logged": bool(st.get("trace"))}


def markdown(result: dict, run_name: str, years=YEARS) -> str:
    lines_ = result["lines"]
    st = result.get("run_status") or {}
    count = {s: sum(r["status"] == s for r in lines_)
             for s in ("PASS", "FLAG", "HELD", "NOT IN RUN", "NO MODEL YEARS", "NO EIA VALUE")}
    out = [f"# Fidelity against AEO2026: {run_name}", "",
           f"Generated {date.today()} by `scripts/aeo_fidelity.py`. Ours against EIA's AEO2026 reference (cb2026 restart).",
           f"Prices in {result['dollar_year']} dollars (EIA's GDP deflator). First model year {result['first_model_year']}: "
           f"2025 is history in both columns and is not graded.",
           "Years the run did not converge: " + (", ".join(map(str, result["not_converged"])) or "none") +
           " (cells marked nc).",
           *([f"Run log: LFMM {st.get('lfmm')}, finished {st.get('finished')}, error {st.get('error')}"
              + ("; a traceback was logged during the run." if st.get("traceback_logged") else ".")] if st else []),
           "",
           f"Lines: {count['PASS']} pass, {count['FLAG']} flagged, {count['HELD']} held at EIA's value, "
           f"{count['NOT IN RUN']} not in the run's output.", "",
           "Each cell is ours / EIA (percent difference). `!` marks a model year outside the line's tolerance. "
           "Tolerances are in docs/fidelity_report.md.", "",
           "## Worst 15 lines", "",
           "| # | Table | Series | Unit | Worst year | Ours | EIA | Diff | Times tolerance |", "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(worst(result), 1):
        y = r["worst"]["year"]
        c = r["years"][y]
        out.append(f"| {i} | {r['table'].split('.')[0]} | {r['series']} | {r['unit']} | {y} | {_fmt(c['ours'])} | "
                   f"{_fmt(c['eia'])} | {_pct(c['diff_pct'])} | {r['worst']['times_tol']:.1f} |")
    tables = []
    for r in lines_:
        if r["table"] not in tables:
            tables.append(r["table"])
    for t in tables:
        out += ["", f"## {t}", "", "| Series | Unit | " + " | ".join(map(str, years)) + " | Status | Tolerance |",
                "|---|---|" + "---|" * len(years) + "---|---|"]
        for r in (x for x in lines_ if x["table"] == t):
            tol = f"{r['tolerance_pct']:g}% or {r['tolerance_floor']:g}"
            out.append(f"| {r['series']} | {r['unit']} | " + " | ".join(_cell(r["years"][y]) for y in years) +
                       f" | {r['status']} | {tol} |")
    return "\n".join(out) + "\n"


def to_json(result: dict, run_name: str, run_path: str) -> dict:
    return {"schema": "nems-open-fidelity/1", "generated": str(date.today()), "run": run_name, "run_path": run_path,
            "baseline": "AEO2026 reference (cb2026 restart)", "tolerance": TOLERANCE,
            "dollar_year": result["dollar_year"], "first_model_year": result["first_model_year"],
            "not_converged": result["not_converged"], "run_status": result.get("run_status"),
            "worst": [{"table": r["table"], "series": r["series"], **r["worst"]} for r in worst(result)],
            "lines": [{**r, "years": {str(y): c for y, c in r["years"].items()}} for r in result["lines"]]}


def latest(showroom: Path) -> Path:
    """The newest reference.npz in a showroom folder or its old-* folders."""
    found = [p for p in [showroom / "reference.npz", *showroom.glob("old-*/reference.npz")] if p.exists()]
    if not found:
        raise FileNotFoundError(f"no reference.npz under {showroom}")
    return max(found, key=lambda p: p.stat().st_mtime)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", type=Path, help="a saved run (full_model.save_run .npz)")
    g.add_argument("--latest", type=Path, help="a showroom folder: use its newest reference.npz")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "fidelity")
    ap.add_argument("--name", help="report name (default: the run's folder and file name)")
    ap.add_argument("--dollar-year", type=int, default=2025)
    a = ap.parse_args(argv)
    path = a.run or latest(a.latest)
    name = a.name or f"{path.parent.name}-{path.stem}"
    eia = Eia()
    res = compare(Run(path, eia), eia, dollar_year=a.dollar_year)
    res["run_status"] = run_status(path)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"{name}.md").write_text(markdown(res, name), encoding="utf-8")
    (a.out / f"{name}.json").write_text(json.dumps(to_json(res, name, f"{path.parent.name}/{path.name}"), indent=1), encoding="utf-8")
    print(f"{path} -> {a.out / name}.md, .json")
    for i, r in enumerate(worst(res), 1):
        c = r["years"][r["worst"]["year"]]
        print(f"{i:2}. {r['status']:4} {r['table'].split('.')[0]:8} {r['series'][:70]:70} {r['worst']['year']} "
              f"{_fmt(c['ours']):>8} vs {_fmt(c['eia']):>8} ({_pct(c['diff_pct'])}, {r['worst']['times_tol']:.1f}x tol)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
