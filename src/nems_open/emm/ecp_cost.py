"""What ECP charges a build column, and what building one year earlier costs (uecp.f EP$BDSP, EP$INT, CALC_STORAGE_VAL;
ecp.ams Calculate_INTBLDCOSTS, Calculate_STORAGECOSTS and the EP$BDSP costs at 6100-6300).

A build column of ECP year E costs, in nominal present value over the UNFPH (30) year horizon,

    (installed cost x CAP + transmission) / CRF(EPDSCRT, 30 - OLYEAR + 1) x PWF(OLYEAR) + PVFOM - PVSOM

with OLYEAR 2 for planning year 1 (online E + 1) and 3 for planning year 2. Installed cost is EPINCST's book value at
the pre-tax cost of capital, CAP is EPCNBLD's capacity payment (20-year debt, tax depreciation with the year-1 bonus),
transmission is EPCOVR x EPCCRF and EPCFOM, PVSOM the production tax credit. Debt and equity rates carry UPNIRTEY and
UPNRRTEY (EP$SUBFIN): 3 points for wind online 2026-2029, solar 2026-2028 and storage 2026-2036 (ecpdaty.xlsx FINANCIAL),
in planning year 2 the present-value share of the tail years (E + 2 on) inside that window.

Everything is returned in 1987$/kW of the online year, as one year's operating costs are: ECP discounts its planning
year 2 operating costs by PWF(2) and inflates them by UPGNPD(E + 1), so nominal present values are divided by both.
Checked against the columns of EIA's own 2030 solve in tests/test_ecp_cost.py.
"""

from functools import lru_cache

import numpy as np

from nems_open.emm import technology
from nems_open.paths import INPUT
from nems_open.xlsx_ranges import named_ranges

UNFPH, UNXPH, UNAPH = 30, 3, 7          # emmcntl.txt %ECP PARAMS%; UNAPH as in the 2030 composite
FIRST_YEAR = 1990
LAST_YEAR = 2050


def crf(rate, n):
    return rate / (1.0 - (1.0 + rate) ** -n)


def deflator(snapshot, year: int) -> float:
    """UPGNPD: MC_JPGDP (1987 = 1), past 2050 at the growth of its last 20 years."""
    jp = np.asarray(snapshot["MACOUT/mc_jpgdp"], dtype=float).ravel()
    last = LAST_YEAR - 1987
    if year <= LAST_YEAR:
        return float(jp[max(year - 1987, 0)] / jp[0])
    g = (jp[last] / jp[last - 20]) ** (1.0 / 20.0)
    return float(jp[last] / jp[0] * g ** (year - LAST_YEAR))


@lru_cache(maxsize=1)
def _bonus_depreciation() -> dict:
    """TAXDEPR1: the year-1 depreciation rate by online year (emmcntl.txt %TAXDEPR Y1%)."""
    lines = (INPUT / "emm" / "emmcntl.txt").read_text(encoding="latin-1").splitlines()
    k = next(i for i, l in enumerate(lines) if l.startswith("%TAXDEPR Y1"))
    out = {}
    for l in lines[k + 1:]:
        if l.startswith("#"):
            if out:
                break
            continue
        p = l.replace("'", " ").split()
        out[int(p[0])] = float(p[1])
    return out


def rate_adder(code: str, online: int, rate: float = 0.0, tail: bool = False) -> tuple:
    """(debt, equity) points added to a new plant's financing (EP$SUBFIN CSTDTADJ, CSTEQADJ). `tail`: planning year 2's
    column, the present-value share of the 28 tail years starting in `online` that fall in the window."""
    f = named_ranges(technology.ECPDATY, "FINANCIAL")
    i = technology.ecp_codes().index(code)
    out = []
    for amt, first, last in (("UPNIRTEY", "UPNIRTES", "UPNIRTEL"), ("UPNRRTEY", "UPNRRTES", "UPNRRTEL")):
        a, lo, hi = float(f[amt][i]), int(f[first][i]), int(f[last][i])
        if not tail:
            out.append(a if lo <= online <= hi else 0.0)
            continue
        w = [(1.0 + rate) ** -k for k in range(1, UNFPH - UNXPH + 2)]
        out.append(a * sum(wk for k, wk in enumerate(w) if lo <= online + k <= hi) / sum(w))
    return tuple(out)


def metal_index(snapshot, code: str, year: int) -> float:
    """UPANNADJ: half the metals price index over its ULRSYR (2023) value (udat.f 13307-13362), times the tariff factor
    EXTANNADJ; past 2050 at the growth of its last ten years."""
    if year > LAST_YEAR:
        g = (metal_index(snapshot, code, LAST_YEAR) / metal_index(snapshot, code, LAST_YEAR - 10)) ** 0.1
        return metal_index(snapshot, code, LAST_YEAR) * g ** (year - LAST_YEAR)
    wpi = np.asarray(snapshot["MACOUT/mc_wpi10"], dtype=float).ravel()
    o = named_ranges(technology.ECPDATY, "OVERWRT")
    w = float(o["UPADJYRWT"][year - 2020])
    ext = np.asarray(o["EXTANNADJ"], dtype=float).reshape(80, -1)[technology.ecp_codes().index(code), year - 2020]
    ratio = wpi[year - FIRST_YEAR] / deflator(snapshot, year) / (wpi[2023 - FIRST_YEAR] / deflator(snapshot, 2023))
    return (w * ratio + 1.0 - w) * ext


def tail_index(snapshot, code: str, online: int, rate: float) -> float:
    """ANNADJ of planning year 2's column (`online` its first tail year): the present-value average of UPANNADJ over
    E + 2 to E + 6 (the average stops at UNAPH)."""
    w = [(1.0 + rate) ** -k for k in range(1, UNAPH - UNXPH + 2)]
    return sum(wk * metal_index(snapshot, code, online + k) for k, wk in enumerate(w)) / sum(w)


def capacity_payment(debt: float, equity: float, share: float, tax: float, ratio: float, bonus: float, loan: int,
                     life: int) -> float:
    """EPCNBLD (uread.f 1429-1500): yearly payment per $ of installed cost. `ratio`: tax basis over book value.
    `bonus`: the year-1 depreciation, 1.0 from 2026, which is all of it."""
    pvdpp = share / loan / crf(equity, loan)
    pvint = share * debt / equity * (1.0 - (1.0 - (1.0 + equity) ** -loan) / (loan * equity))
    pvtb = bonus / (1.0 + equity) * ratio
    return ((1.0 - share) / (1.0 - tax) + pvint - tax / (1.0 - tax) * pvtb + pvdpp / (1.0 - tax)) * crf(equity, life)


def financing(snapshot, year: int, code: str) -> tuple:
    """(debt, equity, debt share, tax, EPDSCRT) of ECP year `year`: EPUIRT + UPNIPRM (BAA less AA, uefp.f 3476) and
    EPUCRE + UPNRPRM, with EXTRARISK on the UPRSKSW types (util.f 893-902); EPDSCRT carries no type's premium."""
    f = named_ranges(technology.ECPDATY, "FINANCIAL")
    i = year - FIRST_YEAR
    debt = float(snapshot["MACOUT/mc_rmcorpbaa"][i]) / 100.0
    equity = float(snapshot["MACOUT/mc_rmtcm10y"][i]) / 100.0 + 0.0575 * float(f["UPBETA"][0]) + float(f["UPNRPRM"][0])
    share, tax = float(f["UPNFDT"][0]), float(f["UPTXRT"][0])
    rate = share * debt * (1.0 - tax) + (1.0 - share) * equity
    extra = float(snapshot["EMISSION/extrarisk"][i]) if f["UPRSKSW"][technology.ecp_codes().index(code)] > 0 else 0.0
    return debt + extra, equity + extra, share, tax, rate


def build_column(snapshot, code: str, online: int, overnight, fom: float, transmission, transmission_fom,
                 ptc=(0.0, 0.0), cf=0.0, ptc_dollar_year: int = 1992, ptc_years: int = 10) -> dict:
    """Planning year 1's column of ECP year online - 1 and planning year 2's of the same solve.

    overnight: (25,) 1987$/kW of the online year, ITC already off (the same ITC holds for both columns, UPCSB). ptc: the
    credit of the online year and of the year after, $/MWh of ptc_dollar_year. transmission: EPCOVR x EPCCRF, 1987$/kW
    a year; transmission_fom: EPCFOM (left out of storage, CALC_STORAGE_VAL). Returns, in 1987$/kW: `first` and `second`
    (the two columns' costs), `capital` (the first column's installed-cost part, which the elasticity steps scale) and
    `annuity` (what spreads a cost over the 29 years online at constant real value)."""
    e = online - 1
    debt0, equity0, share, tax, rate = financing(snapshot, e, code)
    params = named_ranges(technology.ECPDATY, "COSTPERF")
    codes = technology.ecp_codes()
    i = codes.index(code)
    clt, loan, life = int(params["UPCLYR"][i]), int(params["UPNLLF"][i]), int(params["UPNCLF"][i])
    profile = np.asarray(params["UPCPRO"], dtype=float).reshape(len(codes), -1)[i]
    unit = deflator(snapshot, online) * (1.0 + rate) ** -2
    bonus = _bonus_depreciation().get(min(online, LAST_YEAR), 0.0)
    ovn1 = np.asarray(overnight, dtype=float)
    ovn2 = ovn1 * tail_index(snapshot, code, online + 1, rate) / metal_index(snapshot, code, online)
    out = {}
    for py, ovn in ((1, ovn1), (2, ovn2)):
        ol = py + 1
        add_d, add_e = rate_adder(code, online + py - 1, rate, tail=py == 2)
        debt, equity = debt0 + add_d, equity0 + add_e
        ror = share * debt + (1.0 - share) * equity
        tx = bv = 0.0
        for k in range(1, clt + 1):          # EPINCST: the last construction year is the year before service
            spend = profile[k - 1] * deflator(snapshot, e + (py - 1) + k - clt)
            tx += spend + (bv + 0.5 * spend) * debt * share
            bv += spend + (bv + 0.5 * spend) * ror
        cap = capacity_payment(debt, equity, share, tax, tx / bv, bonus, loan, life)
        spread = (1.0 + rate) ** -ol / crf(rate, UNFPH - ol + 1)
        n = UNFPH - ol + 1
        gnp = np.array([deflator(snapshot, e + ol + j - 2) for j in range(1, n + 1)])
        pv = gnp * np.array([(1.0 + rate) ** -(j + ol - 1) for j in range(1, n + 1)])
        capital = ovn * bv * cap * spread
        wires = np.asarray(transmission, dtype=float) * deflator(snapshot, e + ol - 1) * spread
        fixed = (fom + np.asarray(transmission_fom, dtype=float)) * float(pv.sum())
        credit = 0.0
        if ptc[py - 1] > 0:
            real = ptc[py - 1] / deflator(snapshot, ptc_dollar_year) / (1.0 - tax)
            credit = real * np.asarray(cf, dtype=float) * 8.76 * float(pv[:ptc_years].sum())
        out["first" if py == 1 else "second"] = (capital + wires + fixed - credit) / unit
        if py == 1:
            out["capital"] = capital / unit
            out["annuity"] = float(pv.sum()) / unit
    return out


def one_year_cost(column: dict, step: float = 1.0) -> np.ndarray:
    """What a plant has to earn in its first year online for ECP to build it then, 1987$/kW-year, on a build step that
    costs `step` times the first (EPCCSUP, ESTCPCST: the multiple of the installed cost, paid for the whole horizon).

    ECP's planning year 2 columns of the same type cost step 1 and are unbounded, so the tail can be worth at most what
    that column costs: a first-year build must earn at least the difference of the two in planning year 2. If it earns
    the same real value every year, it must also cover its whole cost spread over its years online. The larger of the
    two. They agree for a type whose cost and credits hold still, and part where a credit or a financing adder runs out
    (a storage plant online in 2031 pays the 3 points for life, the tail's almost none of them) and on the dearer steps,
    which a year's wait avoids."""
    first = column["first"] + (step - 1.0) * column["capital"]
    return np.maximum(first - column["second"], first / column["annuity"])
