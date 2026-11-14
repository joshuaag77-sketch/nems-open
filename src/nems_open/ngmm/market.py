"""A national natural gas market in place of EIA's NGMM (AIMMS): demand in, gas prices out.

Each year the market clears on NGMM's own short-run supply curve (curve.py) through HSM's expected
production Q0 at last year's wellhead price P0:

    supply(P) = Q0 * curve.quantity(P / (P0 * r))
    needed(P) = Q_base + k * (dD + X(P) - X_base)
    X(P)      = X_base * (P / P_base) ** ex          (ex_up above the baseline price, ex_down below)

dD is the change in US gas use from the baseline (QBLK/qngas, all sectors, in Bcf), X is gross
exports, r is the baseline's residual (the national curve passes exactly through EIA's realised point),
and k scales use into dry production (lease, plant and pipeline fuel). P is the average wellhead price
(NGTDMREP/ngscrv_p). Henry Hub moves with it dollar for dollar times `hh`; every delivered gas price
(MPBLK png*, pgf*, pgi*) moves by its own fitted share of the Henry Hub change.

Over years, Q0 follows the run's prices: Q0 = Q0_ref * exp(eps * mean dlog(P / P_ref) over the last
`lag` years), eps calibrated on EIA's seven demand cases (fit.py). Without HSM the reference is cb2026
(Q0_ref = Q0_base, P_ref = P_base). With HSM (set_hsm) it is HSM's expected production on a price path
and that path: HSM moves the level, the fitted response keeps the price pinned between HSM runs (a
fixed production path alone leaves the price level free to drift, since the curve is centred on last
year's price).

All prices are 1987 dollars (wellhead per Mcf, the rest per MMBtu) like the restart file. With baseline
demand every price is cb2026's to rounding.
"""
import json
from pathlib import Path

import numpy as np

from nems_open.ngmm import curve, data
from nems_open.supply_standin.data import FIRST_YEAR, US

COEFFICIENTS = Path(__file__).with_name("coefficients.json")
LO, HI = 0.05, 40.0          # bracket for the clearing price, multiples of the baseline price
EXPORTS = "NGTDMREP/ngexpvol"  # (4, 61): Canada, Mexico, LNG, total; Bcf


def gas_price_names(arrays: dict) -> list[str]:
    return sorted(k for k in arrays if k.startswith(("MPBLK/png", "MPBLK/pgf", "MPBLK/pgi")))


class GasMarket:
    def __init__(self, baseline: str = "cb2026", coefficients: Path = COEFFICIENTS, base: dict | None = None):
        b = data.load(baseline)
        c = json.loads(Path(coefficients).read_text())
        self.k, self.hh_per_wellhead = c["k"], c["hh_per_wellhead"]
        self.ex_up, self.ex_down = c["exports_up"], c["exports_down"]
        self.eps, self.lag = c["eps_long_run"], int(c["lag"])
        self.pass_through = {k: np.asarray(v) for k, v in c["pass_through"].items()}
        g = lambda k: b["NGTDMREP/" + k]
        self.Qb, self.Q0b, self.Pb, self.P0b = g("ngscrv_q"), g("ngscrv_q0"), g("ngscrv_p"), g("ngscrv_p0")
        self.HHb = g("oghhprng")
        self.Xb = b[EXPORTS][3]
        self.cf = b["CONVFACT/cfngc"]
        # The delivered prices and gas use the loop starts from (a blend of cases may replace cb2026's).
        src = base if base is not None else b
        self.qngas_b = np.asarray(src["QBLK/qngas"][US], dtype=np.float64)
        self.prices_b = {k: np.asarray(src[k], dtype=np.float64) for k in gas_price_names(b) if k in src}
        ok = (self.Q0b > 0) & (self.P0b > 0)
        self.r = np.where(ok, self.Pb / np.where(ok, self.P0b * curve.price(np.where(ok, self.Qb / np.where(ok, self.Q0b, 1), 1)), 1), 1.0)
        self.first = int(np.argmax(self.Q0b > 0))   # years before EIA's first NGMM year keep the baseline
        self.reset()

    def reset(self):
        """Back to the baseline's price history and expected production."""
        self.P = self.Pb.copy()        # settled wellhead price by year
        self.hsm_ratio = None          # HSM's expected production on a price path / on cb2026's
        self.hsm_P = self.Pb           # the wellhead path HSM saw
        self.last = None

    # State ---------------------------------------------------------------------------------------

    def set_hsm(self, ratio, wellhead=None):
        """Expected production from an HSM run on wellhead prices `wellhead` (61,; default cb2026's):
        Q0_ref = Q0_base * ratio. None goes back to cb2026 as the reference."""
        if ratio is None:
            self.hsm_ratio, self.hsm_P = None, self.Pb
            return
        self.hsm_ratio = np.nan_to_num(np.asarray(ratio, dtype=np.float64), nan=1.0)
        self.hsm_P = self.Pb.copy() if wellhead is None else np.asarray(wellhead, dtype=np.float64).copy()

    def settle(self, j: int, wellhead: float | None = None):
        """Record year j's wellhead price (the last clearing's by default): next year's P0 and Q0 read it."""
        self.P[j] = self.last["wellhead"][j] if wellhead is None else wellhead

    def wellhead_ratio(self) -> np.ndarray:
        """The run's settled wellhead prices over cb2026's (61,), 1 where there is no price: what HSM is handed."""
        return np.divide(self.P, self.Pb, out=np.ones(61), where=self.Pb > 0)

    def p0(self) -> np.ndarray:
        """Last year's wellhead price, as NGMM centres its curve (the baseline's P0 / P ratio kept)."""
        out = self.P0b.copy()
        out[1:] = self.P0b[1:] * np.divide(self.P[:-1], self.Pb[:-1], out=np.ones(60), where=self.Pb[:-1] > 0)
        return out

    def q0(self) -> np.ndarray:
        ref = self.hsm_P
        d = np.log(np.divide(self.P, ref, out=np.ones(61), where=(ref > 0) & (self.P > 0)))
        lagged = np.zeros(61)
        for j in range(self.lag, 61):
            lagged[j] = d[j - self.lag:j].mean()
        q = self.Q0b if self.hsm_ratio is None else self.Q0b * self.hsm_ratio
        return q * np.exp(self.eps * lagged)

    # The clearing ---------------------------------------------------------------------------------

    def exports(self, p) -> np.ndarray:
        ratio = np.divide(p, self.Pb, out=np.ones(61), where=self.Pb > 0)
        ex = np.where(ratio > 1, self.ex_up, self.ex_down)
        return self.Xb * ratio ** ex

    def clear(self, qngas_us) -> dict:
        """Wellhead price, Henry Hub, production and exports for US gas use qngas_us (61,), trillion Btu."""
        dD = (np.asarray(qngas_us, dtype=np.float64) - self.qngas_b) / self.cf
        q0, p0 = self.q0(), self.p0()
        live = (self.Q0b > 0) & (self.Pb > 0) & (self.P0b > 0)
        live[:max(self.first, 1)] = False   # no curve before NGMM's first year (and none without a year before)

        def excess(p):
            supply = q0 * curve.quantity(p / (p0 * self.r))
            needed = self.Qb + self.k * (dD + self.exports(p) - self.Xb)
            return supply - needed

        lo, hi = self.Pb * LO, self.Pb * HI
        for _ in range(60):   # bisection on log price, every year at once (supply - needed rises with p)
            mid = np.sqrt(lo * hi)
            up = excess(mid) < 0
            lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
        p = np.where(live, np.sqrt(lo * hi), self.Pb)
        hh = self.HHb + self.hh_per_wellhead * (p - self.Pb)
        out = {"wellhead": p, "henry_hub": hh, "production": q0 * curve.quantity(p / (p0 * self.r)),
               "expected": q0, "exports": self.exports(p)}
        self.last = out
        return out

    def prices(self, qngas_us) -> dict[str, np.ndarray]:
        """Every MPBLK gas price (11, 61) for US gas use qngas_us: the baseline plus its share of the Henry Hub move."""
        dhh = self.clear(qngas_us)["henry_hub"] - self.HHb
        out = {}
        for k, pb in self.prices_b.items():
            b = self.pass_through.get(k, np.ones(11))[:, None]
            out[k] = np.where(pb > 0, np.maximum(pb + b * dhh, 0.05 * pb), pb)
        return out

    def simulate(self, qngas_us, start_year: int = 2027) -> dict:
        """Year by year, as the loop runs it, for a fixed path of gas use. Returns the last clearing."""
        self.reset()
        for j in range(start_year - FIRST_YEAR, 61):
            self.clear(qngas_us)
            self.settle(j)
        return self.clear(qngas_us)
