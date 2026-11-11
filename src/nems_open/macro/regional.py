"""Regional economy: commercial floorspace, industrial output and employment by census division.

EIA's REGIONAL and IO subroutines (input/macro/mcevsubs.prg) work in two steps, and so does this:
1. a national total moves with the national economy (floorspace through a VAR, industry output
   through the national model);
2. the nine census divisions get fixed long-run shares of that total (the {region}_{type}_int and
   {region}_{industry}_outsh series, which live in S&P's workfile). Here the shares are read from
   EIA's own reference run (cb2026), which reproduces them exactly.

Step 1 is replaced by elasticities of the log gap to the reference. Floorspace follows the log gap in
real GDP (MC_GDPR). Industry output and employment follow that gap plus the log gap in the industrial
delivered-energy price (a Laspeyres index over the MPBLK/QBLK "in" fuels), one pair of elasticities per
industry, fitted by ridge regression on lowogs, hm2026 and lm2026. highogs is held out in the tests.
Without the price term (GDP alone) the held-out industry error was 0.040 against 0.045 for no change;
with it, 0.037.

MC_COMMFLSP is stored as annual log growth (dlog) per division and building type, 9 types populated;
MC_REVIND and MC_EMPNA are levels, the 9 divisions in rows 0 to 8 and the US in row 10.
"""

import glob
from pathlib import Path

import numpy as np

from nems_open.paths import UPSTREAM

YEARS = np.arange(1990, 2051)
FIT = slice(36, 61)  # 2026 to 2050
DIVISIONS = 9
US = 10
RIDGE = 0.01
PSCALE = 10.0
KEYS = ("mc_gdpr", "mc_commflsp", "mc_revind", "mc_empna")


def restart_path(case: str) -> Path | None:
    hits = sorted(glob.glob(str(UPSTREAM / "output" / "aeo2026" / case / "*" / "restart.*")))
    return Path(hits[-1]) if hits else None


def _industrial_names(keys) -> list[str]:
    keys = set(keys)
    return sorted(k for k in keys if k.startswith("MPBLK/p") and k.endswith("in") and "QBLK/q" + k[7:] in keys)


def load_case(case: str) -> dict[str, np.ndarray]:
    """MACOUT arrays (lower-case keys) plus the industrial MPBLK prices and QBLK quantities (full names)."""
    path = restart_path(case)
    if path is None:
        raise FileNotFoundError(case)
    z = np.load(path, allow_pickle=False)
    out = {k: np.asarray(z["MACOUT/" + k], dtype=float) for k in KEYS}
    for k in _industrial_names(z.files):
        out[k] = np.asarray(z[k], dtype=float)
        out["QBLK/q" + k[7:]] = np.asarray(z["QBLK/q" + k[7:]], dtype=float)
    return out


def industrial_price_gap(prices, ref) -> np.ndarray:
    """Log of the industrial delivered-energy price index against the reference, annual 1990 to 2050.

    prices: any mapping holding MPBLK/p??in as (11, 61) arrays; ref: a case dict from load_case (its
    quantities are the Laspeyres weights). The US row (index 10) is used.
    """
    names = [k for k in ref if k.startswith("MPBLK/p") and k in prices]
    num = sum(np.nan_to_num(np.asarray(prices[k], float)[US] * ref["QBLK/q" + k[7:]][US]) for k in names)
    den = sum(np.nan_to_num(ref[k][US] * ref["QBLK/q" + k[7:]][US]) for k in names)
    return np.log(np.where(den > 0, num / np.where(den > 0, den, 1.0), 1.0))


def gdp_gap(scen_gdpr, ref_gdpr) -> np.ndarray:
    """Log gap of real GDP to the reference, annual, 1990 to 2050."""
    return np.log(np.asarray(scen_gdpr, float) / np.asarray(ref_gdpr, float))


def _slope(y: np.ndarray, g: np.ndarray) -> np.ndarray:
    """Least-squares slope through the origin of each row of y (rows x years) on g."""
    return (y * g).sum(-1) / (g * g).sum()


class Regional:
    def __init__(self, reference: dict[str, np.ndarray] | None = None):
        self.ref = reference or load_case("cb2026")
        self.floor_types = np.where(np.abs(self.ref["mc_commflsp"][:DIVISIONS, :, 40]).sum(0) > 0)[0]
        self.beta_floor = 0.0
        self.e_ind = np.zeros((2, self.ref["mc_revind"].shape[1]))
        self.e_emp = np.zeros((2, self.ref["mc_empna"].shape[1]))

    def fit(self, *cases: dict[str, np.ndarray], ridge: float = RIDGE) -> "Regional":
        """Floorspace elasticity from the first case; industry output and employment elasticities
        (GDP and industrial price) from all of them."""
        g = gdp_gap(cases[0]["mc_gdpr"], self.ref["mc_gdpr"])[FIT]
        self.beta_floor = float(_slope(self.floor_gap(cases[0])[FIT], g))
        gaps = [(gdp_gap(c["mc_gdpr"], self.ref["mc_gdpr"])[FIT], industrial_price_gap(c, self.ref)[FIT]) for c in cases]
        self.e_ind = self._level_elasticity("mc_revind", cases, gaps, ridge)
        self.e_emp = self._level_elasticity("mc_empna", cases, gaps, ridge)
        return self

    def floor_gap(self, scen) -> np.ndarray:
        """Cumulative log gap in US commercial floorspace (mean of the populated divisions and types),
        measured from the end of 2025."""
        t = self.floor_types
        d = scen["mc_commflsp"][:DIVISIONS][:, t] - self.ref["mc_commflsp"][:DIVISIONS][:, t]
        f = np.cumsum(d.mean((0, 1)))
        return f - f[35]

    def _level_elasticity(self, key, cases, gaps, ridge) -> np.ndarray:
        """(2, industries): elasticity to the GDP gap and to the industrial price gap (price scaled by PSCALE
        inside the ridge penalty so both terms are shrunk comparably)."""
        ref = self.ref[key][US][:, FIT]
        ok = ref.min(1) > 0
        X = np.vstack([np.column_stack([g, p / PSCALE]) for g, p in gaps])
        Y = np.vstack([np.log(c[key][US][:, FIT] / np.where(ok[:, None], ref, 1.0)).T for c in cases])
        B = np.linalg.solve(X.T @ X + ridge * np.diag([0.0, 1.0]), X.T @ Y)
        B[1] /= PSCALE
        B[:, ~ok] = 0.0
        return B

    def predict(self, gap: np.ndarray, price_gap: np.ndarray | None = None) -> dict[str, np.ndarray]:
        """Scenario MC_COMMFLSP, MC_REVIND and MC_EMPNA for a log real-GDP gap and a log industrial
        price gap (annual, 1990 to 2050; no price gap means the reference price)."""
        g = np.where(YEARS >= 2026, gap, 0.0)
        p = np.zeros_like(g) if price_gap is None else np.where(YEARS >= 2026, price_gap, 0.0)
        out = {k: self.ref[k].copy() for k in ("mc_commflsp", "mc_revind", "mc_empna")}
        # floorspace: every division and type moves with the US total (fixed shares), so the dlog shifts
        level = self.beta_floor * g
        out["mc_commflsp"][:DIVISIONS][:, self.floor_types] += np.diff(level, prepend=0.0)
        for key, e in (("mc_revind", self.e_ind), ("mc_empna", self.e_emp)):
            f = np.exp(np.outer(e[0], g) + np.outer(e[1], p))  # (industries, years)
            out[key][:DIVISIONS] *= f
            out[key][US] *= f
        return out
