"""A fitted stand-in for EIA's Liquid Fuels Market Module (LFMM).

EIA's LFMM is a GAMS linear program of US refining (models/lfmm, about 1.2 MB of GAMS and 8 MB
of GDX data, driven by source/refine.f). Porting it needs a GDX reader and a translation of the
LP; docs/lfmm_plan.md has the path. Until then this module gives the rest of the loop the two
things it needs from LFMM, fitted on EIA's own AEO2026 runs:

1. Refinery-gate product prices. For each product p (gasoline, diesel, jet, residual) the US
   price moves from the baseline by

       dP_p = dBrent / heat_p + a_p * P0_p * dlog Q_p

   Crude passes through dollar for dollar per barrel of product (set, as in the supply stand-in;
   freeing it fits 0.7 to 1.7 and holds out worse). a_p, the response to the product's own US
   demand, is fitted and kept at zero or above. The same level change goes to every sector's
   and every region's price of the product: what differs between them is distribution, taxes
   and margins, which LFMM holds fixed.
2. Refinery fuel use (QBLK q*rf). Total refinery energy and purchased electricity move with US
   demand for the four products; natural gas takes a share of the remaining fuel that moves
   with the price of gas to industry relative to Brent; refinery petroleum (still gas, coke,
   other) is the rest:

       dlog Q_ts = e_ts * dlog Q_liquids        dlog Q_el = e_el * dlog Q_liquids
       dlog s_ng = e_share * dlog(P_gas_ind / Brent)
       Q_ng = s_ng * (Q_ts - Q_el - Q_coal - Q_bio),  Q_tp = the rest

   Every region moves by the US ratio of each fuel.

With baseline inputs it returns the baseline exactly. Grade: amber (a fit, not EIA's LP).
Coefficients: fit.py, stored in coefficients.json; fit quality in docs/lfmm_fit.md.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from nems_open.supply_standin.data import US, load_case

COEFFICIENTS = Path(__file__).with_name("coefficients.json")

# product -> (fuel codes whose demand drives it, MMBtu per barrel, US reference price,
#             the MPBLK fuel codes priced from it)
PRODUCTS = {
    "mg": (("mg",), 5.053, "MPBLK/pmgas", ("mg",)),
    "ds": (("ds",), 5.774, "MPBLK/pdsas", ("ds",)),
    "jf": (("jf",), 5.670, "MPBLK/pjftr", ("jf",)),
    "rs": (("rl", "rh"), 6.287, "MPBLK/prsas", ("rl", "rh", "rs")),
}
SECTORS = ("rs", "cm", "in", "tr", "el")
# Refinery fuel the stand-in moves (QBLK/q<f>rf); coal and biomass keep the baseline.
RF_FITTED = ("tp", "ng", "el")
RF_FIXED = ("cl", "bm")
MAX_GAS_SHARE = 0.95
# Components of refinery petroleum that move with QBLK/qtprf.
RF_PETROLEUM = ("sg", "pc", "ot", "ds", "rs", "lg", "rl")
# Refinery fuel is counted inside the industrial sector: QBLK/q<f>in includes QBLK/q<f>rf.
RF_IN_INDUSTRY = ("ng", "el", "sg", "pc", "ot", "ds", "rs", "lg", "rl")
DLOG_CLIP = 1.0
FLOOR = 0.01   # a product price never falls below 1% of its baseline


def dlog(new, base):
    new, base = np.asarray(new, dtype=np.float64), np.asarray(base, dtype=np.float64)
    ok = (new > 0) & (base > 0)
    out = np.zeros(np.broadcast(new, base).shape)
    np.log(np.where(ok, new, 1.0) / np.where(ok, base, 1.0), out=out, where=ok)
    return np.clip(out, -DLOG_CLIP, DLOG_CLIP)


def product_demand(q: dict, product: str) -> np.ndarray:
    """US demand for one product summed over the end-use and power sectors, trillion Btu, (61,)."""
    fuels = PRODUCTS[product][0]
    return sum(q[f"QBLK/q{f}{s}"][US] for f in fuels for s in SECTORS if f"QBLK/q{f}{s}" in q)


def liquids_demand(q: dict) -> np.ndarray:
    return sum(product_demand(q, p) for p in PRODUCTS)


def price_regressors(product: str, q: dict, brent, base: dict) -> dict[str, np.ndarray]:
    """US regressors for one product's price change, (61,) each, 1987 $/MMBtu."""
    heat, ref = PRODUCTS[product][1], PRODUCTS[product][2]
    p0 = base[ref][US]
    return {
        "crude": (np.asarray(brent, dtype=np.float64) - base["INTOUT/brent_price"]) / heat,
        "own": p0 * dlog(product_demand(q, product), product_demand(base, product)),
    }


def gas_share(q: dict) -> np.ndarray:
    """US natural gas share of refinery gas plus petroleum fuel, (61,)."""
    ng, tp = q["QBLK/qngrf"][US], q["QBLK/qtprf"][US]
    return np.divide(ng, ng + tp, out=np.zeros_like(ng), where=ng + tp > 0)


def rf_regressors(q: dict, brent, png_in, base: dict) -> dict[str, np.ndarray]:
    """US regressors for refinery fuel, (61,) each."""
    return {"liq": dlog(liquids_demand(q), liquids_demand(base)),
            "gas_crude": dlog(np.asarray(png_in) / np.asarray(brent),
                              base["MPBLK/pngin"][US] / base["INTOUT/brent_price"])}


def fold(start: np.ndarray, delta: np.ndarray) -> np.ndarray:
    """Industrial use plus the refinery change, floored at zero where it started at zero or above
    (some of EIA's industrial entries are negative; those pass through)."""
    out = start + delta
    return np.where((out < 0) & (start >= 0), 0.0, out)


@dataclass
class LfmmResult:
    prices: dict[str, np.ndarray]      # MPBLK/p<product><sector> for the LFMM products, (11, 61)
    refinery: dict[str, np.ndarray]    # QBLK/q<f>rf, (11, 61), trillion Btu
    industry: dict[str, np.ndarray]    # QBLK/q<f>in with the refinery change folded in, (11, 61)


class LfmmStandin:
    def __init__(self, baseline: str = "cb2026", base: dict | None = None, coefficients: Path = COEFFICIENTS):
        self.base = base if base is not None else load_case(baseline)
        coef = json.loads(Path(coefficients).read_text())
        self.price_coef = {p: v["coef"] for p, v in coef["prices"].items()}
        self.rf_coef = {f: v["coef"] for f, v in coef["refinery"].items()}

    def price_change(self, q: dict, brent) -> dict[str, np.ndarray]:
        """US level change in each product's price, 1987 $/MMBtu, (61,)."""
        out = {}
        for p in PRODUCTS:
            x = price_regressors(p, q, brent, self.base)
            out[p] = x["crude"] + self.price_coef[p]["own"] * x["own"]
        return out

    def refinery_us(self, q: dict, brent, png_in) -> dict[str, np.ndarray]:
        """US refinery fuel use, trillion Btu, (61,): ts, el, ng, tp."""
        b, c = self.base, self.rf_coef
        x = rf_regressors(q, brent, png_in, b)
        ts = b["QBLK/qtsrf"][US] * np.exp(c["ts"]["liq"] * x["liq"])
        el = b["QBLK/qelrf"][US] * np.exp(c["el"]["liq"] * x["liq"])
        fuel = np.maximum(ts - el - sum(b[f"QBLK/q{f}rf"][US] for f in RF_FIXED), 0.0)
        share = np.minimum(gas_share(b) * np.exp(c["ng"]["gas_crude"] * x["gas_crude"]), MAX_GAS_SHARE)
        ng = share * fuel
        return {"ts": ts, "el": el, "ng": ng, "tp": fuel - ng}

    def solve(self, q: dict | None = None, brent=None, png_in=None, industry: dict | None = None) -> LfmmResult:
        """Product prices and refinery fuel use.

        q: QBLK arrays (11, 61) with end-use and power-sector demand by fuel; missing keep the
            baseline. brent: 1987 $/bbl by year (61,); default the baseline's. png_in: US gas
            price to industry, 1987 $/MMBtu (61,); default the baseline's.
        industry: QBLK/q<f>in arrays to fold the refinery change into (the demand side's own
            industrial use, which carries the baseline's refinery fuel); default the baseline's.
        """
        base = self.base
        q = {**{k: v for k, v in base.items() if k.startswith("QBLK/")}, **(q or {})}
        brent = base["INTOUT/brent_price"] if brent is None else np.asarray(brent, dtype=np.float64)
        png_in = base["MPBLK/pngin"][US] if png_in is None else np.asarray(png_in, dtype=np.float64)

        prices = {}
        for p, d in self.price_change(q, brent).items():
            for fuel in PRODUCTS[p][3]:
                for name in (k for k in base if k.startswith(f"MPBLK/p{fuel}") and len(k) == 11):
                    b = base[name]
                    prices[name] = np.where(b > 0, np.maximum(b + d, FLOOR * b), b)

        us = self.refinery_us(q, brent, png_in)
        ratio = {f: np.divide(us[f], base[f"QBLK/q{f}rf"][US], out=np.ones(61), where=base[f"QBLK/q{f}rf"][US] > 0)
                 for f in RF_FITTED}
        refinery = {}
        for f in RF_FITTED:
            refinery[f"QBLK/q{f}rf"] = base[f"QBLK/q{f}rf"] * ratio[f]
        for f in RF_PETROLEUM:
            if f"QBLK/q{f}rf" in base:
                refinery[f"QBLK/q{f}rf"] = base[f"QBLK/q{f}rf"] * ratio["tp"]
        refinery["QBLK/qtsrf"] = base["QBLK/qtsrf"] + sum(
            refinery[f"QBLK/q{f}rf"] - base[f"QBLK/q{f}rf"] for f in RF_FITTED)

        industry = industry or {}
        ind = {}
        for f in RF_IN_INDUSTRY:
            k, r = f"QBLK/q{f}in", f"QBLK/q{f}rf"
            if k in base and r in refinery:
                start = np.asarray(industry.get(k, base[k]), dtype=np.float64)
                ind[k] = fold(start, refinery[r] - base[r])
        return LfmmResult(prices, refinery, ind)

    def solve_year(self, j: int, q: dict, col: dict, brent, png_in: float) -> LfmmResult:
        """One year for the loop: q holds the loop's (11, 61) quantities, col the demand side's
        fresh column for year index j (it overrides q there). Returns columns (11,) for year j:
        product prices, refinery fuel, and industrial fuel with the refinery change folded in.
        Industrial use fresh from the demand side (in col) carries the baseline's refinery fuel;
        use already in q carries what the last call put there, so the fold never doubles. brent: 1987 $/bbl, png_in: US gas
        price to industry, 1987 $/MMBtu, both for year j."""
        keys = {f"QBLK/q{f}{s}" for p in PRODUCTS for f in PRODUCTS[p][0] for s in SECTORS}
        qq = {}
        for k in keys:
            if k in q:
                a = np.array(q[k], dtype=np.float64)
                if k in col:
                    a[:, j] = col[k]
                qq[k] = a
        b = self.base
        br, pg = b["INTOUT/brent_price"].copy(), b["MPBLK/pngin"][US].copy()
        br[j], pg[j] = brent, png_in
        industry = {k: (col[k] if k in col else q[k][:, j]) for f in RF_IN_INDUSTRY
                    if (k := f"QBLK/q{f}in") in b}
        r = self.solve(qq, br, pg)
        ind = {}
        for f in RF_IN_INDUSTRY:
            k, rf = f"QBLK/q{f}in", f"QBLK/q{f}rf"
            if k in industry and rf in r.refinery:
                held = b[rf][:, j] if k in col else q[rf][:, j]
                ind[k] = fold(np.asarray(industry[k], dtype=np.float64), r.refinery[rf][:, j] - held)
        return LfmmResult({k: v[:, j] for k, v in r.prices.items()},
                          {k: v[:, j] for k, v in r.refinery.items()}, ind)
