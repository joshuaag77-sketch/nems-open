"""Regional economy: commercial floorspace, industrial output and employment by census division.

EIA's REGIONAL and IO subroutines (input/macro/mcevsubs.prg) work in two steps, and so does this:
1. a national total moves with the national economy (floorspace through a VAR, industry output
   through the national model);
2. the nine census divisions get fixed long-run shares of that total (the {region}_{type}_int and
   {region}_{industry}_outsh series, which live in S&P's workfile). Here the shares are read from
   EIA's own reference run (cb2026), which reproduces them exactly.

Step 1 is replaced by one elasticity of the log gap to the reference against the log gap in real GDP
(MC_GDPR), fitted on lowogs. highogs is held out in the tests; hm2026 and lm2026 (EIA's own high and
low macro cases) are a second check on the GDP link.

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
KEYS = ("mc_gdpr", "mc_commflsp", "mc_revind", "mc_empna")


def restart_path(case: str) -> Path | None:
    hits = sorted(glob.glob(str(UPSTREAM / "output" / "aeo2026" / case / "*" / "restart.*")))
    return Path(hits[-1]) if hits else None


def load_case(case: str) -> dict[str, np.ndarray]:
    path = restart_path(case)
    if path is None:
        raise FileNotFoundError(case)
    z = np.load(path, allow_pickle=False)
    return {k: np.asarray(z["MACOUT/" + k], dtype=float) for k in KEYS}


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
        self.e_ind = np.zeros(self.ref["mc_revind"].shape[1])
        self.e_emp = np.zeros(self.ref["mc_empna"].shape[1])

    def fit(self, scen: dict[str, np.ndarray]) -> "Regional":
        g = gdp_gap(scen["mc_gdpr"], self.ref["mc_gdpr"])[FIT]
        self.beta_floor = float(_slope(self.floor_gap(scen)[FIT], g))
        self.e_ind = self._level_elasticity("mc_revind", scen, g)
        self.e_emp = self._level_elasticity("mc_empna", scen, g)
        return self

    def floor_gap(self, scen) -> np.ndarray:
        """Cumulative log gap in US commercial floorspace (mean of the populated divisions and types),
        measured from the end of 2025."""
        t = self.floor_types
        d = scen["mc_commflsp"][:DIVISIONS][:, t] - self.ref["mc_commflsp"][:DIVISIONS][:, t]
        f = np.cumsum(d.mean((0, 1)))
        return f - f[35]

    def _level_elasticity(self, key, scen, g) -> np.ndarray:
        ref, sc = self.ref[key][US][:, FIT], scen[key][US][:, FIT]
        ok = ref.min(1) > 0
        e = np.zeros(ref.shape[0])
        e[ok] = _slope(np.log(sc[ok] / ref[ok]), g)
        return e

    def predict(self, gap: np.ndarray) -> dict[str, np.ndarray]:
        """Scenario MC_COMMFLSP, MC_REVIND and MC_EMPNA for a log real-GDP gap (annual, 1990 to 2050)."""
        g = np.where(YEARS >= 2026, gap, 0.0)
        out = {k: self.ref[k].copy() for k in ("mc_commflsp", "mc_revind", "mc_empna")}
        # floorspace: every division and type moves with the US total (fixed shares), so the dlog shifts
        level = self.beta_floor * g
        out["mc_commflsp"][:DIVISIONS][:, self.floor_types] += np.diff(level, prepend=0.0)
        for key, e in (("mc_revind", self.e_ind), ("mc_empna", self.e_emp)):
            f = np.exp(np.outer(e, g))  # (industries, years)
            out[key][:DIVISIONS] *= f
            out[key][US] *= f
        return out
