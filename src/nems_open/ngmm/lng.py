"""The LNG export lever: Policy.lng_exports, US LNG exports in Bcf/d by year.

EIA's NGMM builds LNG export trains itself (nglngexp.txt, LNG_FixedExports_Switch 0 in cb2026). It also has a fixed
mode for side cases (switch 1): each terminal's export capacity comes from the ExogenousAnnualLNGExports table, and
the export curve's lower bound equals its upper bound, so exports are the table. The lever uses that mode.

ogs='aimms': patch_input() rewrites the run copy's nglngexp.txt with switch 1 and a table that puts the path on NGMM's
four lower-48 terminals. Each year's total is split as NGMM's own cb2026 run splits it between the two terminal groups
(LNGTER 3: MD and GA; LNGTER 6: LA and TX_E; reference.pkl, or the restart's NGTDMREP/nalngexp before NGMM's first
year), and within a group by the shares of EIA's own exogenous table in the same file (MD 255.5 to GA 120; LA 3057 to
TX_E 1524). Canada and Alaska stay as they are.

ogs='hsm' / 'ngmm': GasMarket adds the path's difference from cb2026's LNG row (NGTDMREP/ngexpvol) to exports, at any
price, so the gas market has to produce it.

path(): a 2035 level as a path. The difference from EIA's reference in 2035 ramps in linearly from start_year and is
held after, so the path keeps EIA's shape (EIA's reference is 26.8 Bcf/d in 2035 and 30.7 in 2050).
"""

import re

import numpy as np

FIRST_YEAR, NYEARS = 1990, 61
DAYS = 365.0
LNG_ROW = 2                          # NGTDMREP/ngexpvol (4, 61): Canada, Mexico, LNG, total; Bcf a year
GROUPS = {3: {"MD": 255.5, "GA": 120.0}, 6: {"LA": 3057.0, "TX_E": 1524.0}}   # LNGTER -> lngexp, EIA's own shares
TERMINALS = ("GA", "LA", "MD", "TX_E")
TABLE = re.compile(r"^ExogenousAnnualLNGExports := data table\s*\n(.*?)^;", re.M | re.S)
SWITCH = re.compile(r"^LNG_FixedExports_Switch\s*:=\s*0\s*;", re.M)


def eia_bcfd() -> np.ndarray:
    """EIA's reference US LNG exports, Bcf/d by year (61,)."""
    from nems_open.snapshot import Snapshot
    return np.asarray(Snapshot()["NGTDMREP/ngexpvol"], dtype=np.float64)[LNG_ROW] / DAYS


def path(bcfd_2035: float, start_year: int = 2027, by: int = 2035, eia: np.ndarray | None = None) -> np.ndarray:
    """US LNG exports by year, Bcf/d (61,): EIA's reference plus (bcfd_2035 - EIA's 2035), ramped in from start_year."""
    eia = eia_bcfd() if eia is None else np.asarray(eia, dtype=np.float64)
    delta = bcfd_2035 - eia[by - FIRST_YEAR]
    out = eia.copy()
    for y in range(start_year, FIRST_YEAR + NYEARS):
        out[y - FIRST_YEAR] += delta * min(1.0, (y - start_year + 1) / (by - start_year + 1))
    return out


def terminal_table(bcfd, reference: dict | None = None, history=None, first: int = 2015) -> dict[int, dict[str, float]]:
    """{year: {terminal: Bcf a year}}, first to 2050. Group shares come from NGMM's own cb2026 run (reference.pkl's
    "outputs") where it has the year, else from the restart's NGTDMREP/nalngexp (history, (11, 61))."""
    if history is None:
        from nems_open.snapshot import Snapshot
        history = np.asarray(Snapshot()["NGTDMREP/nalngexp"], dtype=np.float64)
    reference = reference or {}
    out = {}
    for y in range(first, FIRST_YEAR + NYEARS):
        j = y - FIRST_YEAR
        if y in reference:
            nal = reference[y]["NGTDMREP_NALNGEXP"]
            g = {t: float(nal.get((t, j + 1), 0.0)) for t in GROUPS}
        else:
            g = {t: float(history[t - 1, j]) for t in GROUPS}
        total = sum(g.values())
        want = float(bcfd[j]) * DAYS
        row = {}
        for t, terms in GROUPS.items():
            share = g[t] / total if total > 0 else 1.0 / len(GROUPS)
            w = sum(terms.values())
            for name, sh in terms.items():
                row[name] = want * share * sh / w
        out[y] = row
    return out


def patch_input(text: str, table: dict[int, dict[str, float]]) -> str:
    """nglngexp.txt with fixed exports: switch 1 and EIA's ExogenousAnnualLNGExports table replaced by `table`."""
    text, n = SWITCH.subn("LNG_FixedExports_Switch :=1;", text, count=1)
    if n != 1:
        raise ValueError("nglngexp.txt: LNG_FixedExports_Switch :=0; not found")
    m = TABLE.search(text)
    if not m:
        raise ValueError("nglngexp.txt: ExogenousAnnualLNGExports table not found")
    tab = "\t"
    body = tab + tab.join(TERMINALS) + "\n" + "".join(
        f"{y}{tab}" + tab.join(f"{table[y][t]:.3f}" for t in TERMINALS) + "\n" for y in sorted(table))
    new = "ExogenousAnnualLNGExports := data table\n! nems-open: Policy.lng_exports (nems_open/ngmm/lng.py)\n" + body + ";"
    return text[:m.start()] + new + text[m.end():]


def added_bcf(bcfd, base_exports) -> np.ndarray:
    """(61,) Bcf a year to add to the gas market's exports: the path over the baseline's LNG row (0 where nan)."""
    base = np.asarray(base_exports, dtype=np.float64)[LNG_ROW]
    d = np.asarray(bcfd, dtype=np.float64) * DAYS - base
    return np.where(np.isnan(d), 0.0, d)
