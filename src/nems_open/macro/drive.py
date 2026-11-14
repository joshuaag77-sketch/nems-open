"""The economy module as run_model sees it: policy and prices in, macro paths for demand out.

macro="frbus" in run_model.run calls scenario_macro once per cycle. Cycle 1 sees only the oil price
(the Brent lever); later cycles also see the previous cycle's delivered-energy prices and quantities,
so use cycles >= 2 for the full energy-bill channel. What it hands to demand:
- gap: log real GDP against the baseline, 61 years from 1990;
- industry_gap: log US industrial output against the baseline (weighted by baseline MC_REVIND);
- commflsp: the scenario MC_COMMFLSP (log floorspace growth by division and building type), which the
  ported commercial module reads;
- price_gap: the industrial energy price gap that drove the industry output.
Residential has no macro input here (households and income are not modelled), and transportation
follows GDP only through the stub elasticities.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nems_open.macro import bridge, frbus_core, regional

_CACHE: dict = {}


@dataclass
class MacroPath:
    gap: np.ndarray
    industry_gap: np.ndarray
    price_gap: np.ndarray
    commflsp: np.ndarray
    channels: str


def _economy(base: dict):
    gdpr = np.asarray(base["MACOUT/mc_gdpr"], float)
    key = ("economy", gdpr.tobytes())
    if key not in _CACHE:
        _CACHE[key] = frbus_core.Economy(gdpr=gdpr)
    return _CACHE[key]


def _regional() -> regional.Regional:
    if "regional" not in _CACHE:
        cases = {c: regional.load_case(c) for c in ("cb2026", "lowogs", "hm2026", "lm2026")}
        _CACHE["regional"] = regional.Regional(cases["cb2026"]).fit(cases["lowogs"], cases["hm2026"], cases["lm2026"])
        _CACHE["ref"] = cases["cb2026"]
    return _CACHE["regional"]


def scenario_macro(base: dict, brent: np.ndarray | None, prices: dict | None = None) -> MacroPath:
    """brent: scenario Brent by year (61,) or None for the baseline's; prices: MPBLK arrays from the
    previous cycle, or None."""
    econ, reg = _economy(base), _regional()
    ratio = pd.Series(1.0, index=np.arange(1990, 2051))
    if brent is not None:
        ratio = pd.Series(np.asarray(brent, float) / np.asarray(base["INTOUT/brent_price"], float), index=ratio.index)
    bill = None
    if prices is not None:
        scen = {k: v for k, v in prices.items() if k.startswith("MPBLK/")}
        bill = bridge.energy_bill_change(scen, base)
    r = econ.run(ratio.loc[frbus_core.FIRST_YEAR : frbus_core.LAST_YEAR], bill, bridge.KAPPA if bill is not None else 0.0)
    g = np.zeros(61)
    ann = np.log(econ.annual(r, "xgdp") / econ.annual(econ.reference, "xgdp"))
    g[frbus_core.FIRST_YEAR - 1990 :] = ann.loc[frbus_core.FIRST_YEAR : frbus_core.LAST_YEAR].values
    pgap = np.zeros(61)
    if prices is not None:
        pgap = regional.industrial_price_gap(prices, _CACHE["ref"])
    out = reg.predict(g, pgap)
    ref_rev = _CACHE["ref"]["mc_revind"]
    # baseline-revenue-weighted over every live row (aggregate rows count too, so big groups weigh more)
    live = ref_rev[regional.US, :, 40] > 0
    ind_gap = np.log(out["mc_revind"][regional.US][live].sum(0) / ref_rev[regional.US][live].sum(0))
    return MacroPath(g, np.nan_to_num(ind_gap), pgap, out["mc_commflsp"], "oil+bill" if bill is not None else "oil")
