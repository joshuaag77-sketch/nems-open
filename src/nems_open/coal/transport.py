"""Transport rate escalators: the RCAF part of SetUpRateEscalators (coal.ams 23927).

Railroad rates escalate with a Rail Cost Adjustment Factor built from seven cost indexes (labor, fuel,
materials and supplies, equipment, depreciation, interest, other) weighted by cmmRCAFwts.txt. Each share
grows with its index from the weight in the RCAF base year (2021); the total, less a productivity pass-through
that depends on how fast US coal output has been falling, gives the yearly escalator, and its running product
is CumRRTransIndx, which scales rail rates.

Safe division (AIMMS `/$`) returns 0 when the divisor is 0.
"""

import numpy as np

from nems_open.coal import inputs
from nems_open.coal.macro import Macro

RCAF_BASE_YR = 2021                     # coal.ams 16877
RR_PRODUCTIVITY = -0.014                # coal.ams 16886: share of 1.4% rail productivity passed to shippers
YEARS = np.arange(1990, 2051)

# index name -> (weight parameter, series)
COMPONENTS = ("labor", "fuel", "materialsup", "equipment", "depreciation", "interest", "other")


def _sdiv(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return np.divide(a, b, out=np.zeros(np.broadcast(a, b).shape), where=b != 0)


def cost_indexes(macro: Macro) -> dict[str, np.ndarray]:
    """The seven cost series by year (1990 to 2050), before rebasing to RCAF_BASE_YR."""
    g = lambda name: np.array([macro.series(name, y) / macro.jpgdp(y) for y in YEARS])
    wpiind = g("MC_WPIIND05")
    return {
        "labor": g("MC_JECIWSP"),
        "fuel": np.array([macro.price("PDSTR", y) for y in YEARS]),
        "materialsup": g("MC_WPI10"),
        "equipment": wpiind,
        "depreciation": g("MC_WPI14"),
        "interest": np.array([macro.series("MC_RLRMCORPPUAA", y) for y in YEARS]),
        "other": wpiind,
    }


def productivity_pass_through(us_prod_prior: np.ndarray) -> np.ndarray:
    """RR_Prdctvty_prct: 0.5 when the 3-year average growth of US output is below -5%, 0 when it is above 0."""
    gr = np.concatenate([[0.0], _sdiv(us_prod_prior[1:], us_prod_prior[:-1]) - 1.0])
    gr[0] = 0.0
    avg = np.zeros_like(gr)
    for i in range(3, len(gr)):
        avg[i] = (gr[i - 1] + gr[i - 2] + gr[i - 3]) / 3.0
    with np.errstate(invalid="ignore"):
        return np.where(avg < -0.05, 0.5, np.where(avg > 0.0, 0.0, (avg / -0.05) ** 0.5 * 0.5))


def rcaf(macro: Macro | None = None, data=None, us_prod_prior: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """TotTransIndx_A, TotTransIndx_B and CumRRTransIndx (FinalRCAFindex) for 1990 to 2050.

    `us_prod_prior` is CQSBB_PriorTot, the prior cycle's US coal output by year (the restart's COALOUT/CQSBB
    total by default).
    """
    macro = macro or Macro()
    data = data or inputs.load()
    idx = cost_indexes(macro)
    b = RCAF_BASE_YR - 1990
    if us_prod_prior is None:
        us_prod_prior = np.asarray(macro.s["COALOUT/CQSBB"][2], float)[: len(YEARS)]

    share = {}
    for name in COMPONENTS:
        rebased = _sdiv(idx[name], idx[name][b])
        growth = np.concatenate([[0.0], _sdiv(rebased[1:], rebased[:-1])])
        wt = data.param(f"wt_{name}")
        base_w = float(wt[(RCAF_BASE_YR,)])
        s = np.zeros(len(YEARS))
        s[: b + 1] = base_w
        for i in range(b + 1, len(YEARS)):
            s[i] = growth[i] * s[i - 1]
        share[name] = s
    total_a = sum(share.values())
    pct = productivity_pass_through(us_prod_prior)
    total_b = np.ones(len(YEARS))
    cum = np.ones(len(YEARS))
    for i in range(b + 1, len(YEARS)):
        total_b[i] = _sdiv(total_a[i], total_a[i - 1]) + RR_PRODUCTIVITY * pct[i]
        cum[i] = total_b[i] * cum[i - 1]
    return dict(years=YEARS, total_a=total_a, total_b=total_b, cum=cum, productivity_pct=pct, **{f"sh_{k}": v for k, v in share.items()})
