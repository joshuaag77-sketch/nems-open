"""State renewable portfolio standards in the capacity LP (uecp.f EP$ST_RPS 40534-41445; ecp.ams EP_ST_RPS_Calculations).

49 tranches (input/emm/rpstranche.txt), each a state requirement with its own qualifying types. ECP writes one row per
tranche and planning year (rGRPSge): credits from existing units of the state (columns X, their generation), from the
generation pool of the EMM regions that carry at least ST_RPS_TOLERANCE of the state's sales (columns N), from other
regions linked to them (columns G, less line losses and no more than the trade on the link), from end-use generation,
and an escape at the alternative compliance payment or 200 1987$/MWh, at least the requirement: the state's share of
each region's sales. One MWh counts in every tranche of one state (TST_STATES), and in one state only.
"""

from functools import lru_cache

import numpy as np

from nems_open.emm import db, plants, regions, technology
from nems_open.paths import INPUT

NUM_R = regions.NUM_EMM
NO_CAP_PRICE = 200.0              # EP$ST_RPS,24: 1987$/MWh where the tranche has no compliance payment
UTILITY_TYPES = ("IOU", "COOP", "MUNI", "OTHR")          # emmcntl.txt %UT_TYPEPCD%; V_EMM_CNTL_STATES sales columns 1-4
END_USE = ("CL", "OL", "OG", "NG", "HY", "GT", "MS", "WD", "SO", "PV", "OT", "WN", "BS")    # unugs.f TC_FUEL_CODES


class Tranche:
    """One tranche: state, id, years, requirement by utility type, price cap, qualifying types."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _tables() -> dict:
    out, name = {}, None
    for line in (INPUT / "emm" / "rpstranche.txt").read_text(encoding="latin-1").splitlines():
        s = line.strip()
        if s.startswith("%"):
            name = s.strip("%").strip()
            out[name] = []
        elif name and s and not s.startswith("#"):
            row, quoted, tok = [], False, ""
            for ch in s:
                if ch == "'":
                    if quoted:
                        row.append(tok.strip())
                        tok = ""
                    quoted = not quoted
                elif ch.isspace() and not quoted:
                    if tok:
                        row.append(tok)
                        tok = ""
                else:
                    tok += ch
            if tok:
                row.append(tok)
            out[name].append(row)
    return out


@lru_cache(maxsize=1)
def tranches() -> tuple:
    t = _tables()
    n, switch = int(t["ST_RPS_NUM"][0][0]), int(t["ST_RPS_NUM"][0][1])
    if not switch:
        return ()
    out = []
    for k in range(1, n + 1):
        g = lambda s: t[f"T{k:02d}_{s}"]
        st = g("STATE")[0]
        chp_n, dg_n, el_n = int(g("CHP_NM")[0][0]), int(g("DG_NUM")[0][0]), int(g("EL_NUM")[0][0])
        rows_n, ut_n = int(g("RPS_NM")[0][0]), int(g("RPS_NM")[0][1])
        years = [int(r[0]) for r in g("RPS_RQ")[:rows_n]]
        vals = np.array([[float(v) for v in r[1:]] for r in g("RPS_RQ")[:rows_n]])
        out.append(Tranche(
            index=k, state=st[0], id=st[1], first=int(st[2]), last=int(st[3]), hold=int(st[4]) == 1,
            cap_year=int(float(st[5])), cap_type={"NA": 0, "Real": 1, "Nominal": 2}[st[6]], title=st[7],
            imports=int(g("IMPORT")[0][0]) > 0,
            chp_total=int(g("CHP_NM")[0][1]), chp={r[0]: float(r[1]) for r in g("CHP_PT")[:chp_n]},
            dg_total=int(g("DG_NUM")[0][1]), dg={r[0]: float(r[1]) for r in g("DG_PT")[:dg_n]},
            types={r[0]: (float(r[1]), float(r[2])) for r in g("EL_PT")[:el_n]},
            utilities=[(r[0].strip(), float(r[1])) for r in g("RPS_UT")[:ut_n]], years=years, values=vals))
    return tuple(out)


@lru_cache(maxsize=1)
def sales() -> dict:
    """H_SALES: {state code: (5, 25) total, IOU, COOP, MUNI, FED sales by EMM region}, and the regions' totals under 'US'."""
    t = db.table("V_EMM_CNTL_STATES")
    cols = ("SALES_TOT", "SALES_IOU", "SALES_COOP", "SALES_MUNI", "SALES_OTHR")
    out = {"US": np.zeros((5, NUM_R))}
    for k in range(len(t["EMM_REG"])):
        r, s = int(t["EMM_REG"][k]), str(t["STATE"][k]).strip()
        if not 1 <= r <= NUM_R or s == "US" or int(t["STATE_ID"][k]) <= 0:
            continue
        v = np.array([float(t[c][k]) for c in cols])
        out.setdefault(s, np.zeros((5, NUM_R)))[:, r - 1] += v
        out["US"][:, r - 1] += v
    return out


def requirement_share(tr: Tranche, year: int) -> np.ndarray:
    """ST_RPS_REQ: the tranche's requirement as a share of each region's sales in `year`, (25,)."""
    if year < tr.years[0]:
        return np.zeros(NUM_R)
    h = sales()
    if tr.state not in h:
        return np.zeros(NUM_R)
    out = np.zeros(NUM_R)
    for j, (u, pct) in enumerate(tr.utilities):
        if year <= tr.years[-1]:
            v = float(np.interp(year, tr.years, tr.values[:, j]))
        else:
            v = float(tr.values[-1, j]) if tr.hold else 0.0
        out += v * pct * h[tr.state][1 + UTILITY_TYPES.index(u)]
    tot = h["US"][0]
    return np.divide(out, tot, out=np.zeros(NUM_R), where=tot > 0)


def price_cap(tr: Tranche, year: int, deflator) -> float:
    """1987$/MWh of the escape column: the compliance payment (EP$ST_RPS,22), else 200."""
    if tr.cap_type == 0:
        return NO_CAP_PRICE
    col = len(tr.utilities)
    if year > tr.years[-1]:
        v = float(tr.values[-1, col]) if tr.hold else 0.0
    else:
        v = float(np.interp(year, tr.years, tr.values[:, col]))
    return v / deflator(tr.cap_year if tr.cap_type == 1 else year) * 1000.0


def mapped_regions(tr: Tranche) -> np.ndarray:
    """ST_RPS_EMM_MAP: regions with more than ST_RPS_TOLERANCE of the state's sales (the largest if those hold too little)."""
    tol = float(_tables()["ST_RPS_NUM"][0][2])
    h = sales().get(tr.state)
    if h is None or h[0].sum() <= 0:
        return np.zeros(NUM_R, dtype=bool)
    share = h[0] / h[0].sum()
    out = share > tol
    if not out.any():
        out[int(np.argmax(share))] = True
    return out


def state_share(tr: Tranche) -> np.ndarray:
    """The state's part of each region's sales (for end-use credits, EP$ST_RPS,8-11)."""
    h = sales()
    if tr.state not in h:
        return np.zeros(NUM_R)
    return np.divide(h[tr.state][0], h["US"][0], out=np.zeros(NUM_R), where=h["US"][0] > 0)


def existing(year: int, cf: dict) -> tuple:
    """Plant-file generation by state, type and region in `year`: ({(state, type): (25,) TWh from units online by the
    state's first tranche's start (the X columns)}, {type: (25,) TWh, all units}). cf: {"WN", "WF", "PV", "PT", "HY":
    (25,) annual capacity factor}; other types run at the plant file's own."""
    u = plants.load_units()
    on = plants.online(year)
    start = {}
    for tr in tranches():
        for k in tr.types:
            start.setdefault((tr.state, k), tr.first)
    types = np.char.strip(np.asarray(u.ecp_type, dtype=str))
    types = np.where(types == "WL", "WN", types)
    states = np.char.strip(np.asarray(u.state, dtype=str))
    r0 = np.clip(np.asarray(u.region) - 1, 0, NUM_R - 1)
    ok = on & (np.asarray(u.region) >= 1) & (np.asarray(u.region) <= NUM_R)
    gen = np.asarray(u.summer_mw, dtype=float) * np.maximum(np.asarray(u.capacity_factor, dtype=float), 0.0) * 8.76e-3
    for k, v in cf.items():
        sel = types == k
        gen = np.where(sel, np.asarray(u.summer_mw, dtype=float) * np.asarray(v)[r0] * 8.76e-3, gen)
    x, pool = {}, {}
    for k in {k for tr in tranches() for k in tr.types}:
        sel = ok & (types == k)
        if not sel.any():
            continue
        p = np.zeros(NUM_R)
        np.add.at(p, r0[sel], gen[sel])
        pool[k] = p
        for s in np.unique(states[sel]):
            if (s, k) not in start:
                continue
            m = sel & (states == s) & (np.asarray(u.online_year) <= start[(s, k)])
            if m.any():
                a = np.zeros(NUM_R)
                np.add.at(a, r0[m], gen[m])
                x[(s, k)] = a
    return x, pool


def rows(snapshot, year: int, req_year: int, sales_twh: np.ndarray, links: dict, cf: dict, deflator) -> dict:
    """Everything EP$ST_RPS needs of one period: the pools (TWh by type and region, less the X columns), the N and G
    columns and their coefficients on the tranche rows, and the rows' constant credits, requirement and escape price.
    `year` the fleet's year, `req_year` the requirement's (ST_RPS_REQ of E + 2 in the tail)."""
    x, pool = existing(year, cf)
    trs = [tr for tr in tranches() if requirement_share(tr, req_year).sum() > 0]
    used = {}
    for (s, k), a in x.items():
        if any(tr.state == s and requirement_share(tr, req_year)[a > 0].sum() > 0 for tr in trs):
            used[k] = used.get(k, np.zeros(NUM_R)) + a
    cogen = np.asarray(snapshot["COGEN/cgtotgennr"], dtype=float)[:NUM_R, min(year, 2050) - 1990] / 1000.0   # (25, 13, 2)
    open_types = ("WN", "PV")                 # the LP's own builds feed these pools
    left = {k: np.maximum(pool.get(k, np.zeros(NUM_R)) - used.get(k, 0.0), 0.0) for k in set(pool) | set(open_types)}
    cols = []                                  # (state, type, from region, to region or -1)
    link = {}
    for li, (a, b) in enumerate(zip(links["exporter"], links["importer"])):
        link.setdefault((int(a), int(b)), []).append(li)
    for s in sorted({tr.state for tr in trs}):
        mine = [tr for tr in trs if tr.state == s]
        mapped = mapped_regions(mine[0])
        has = np.max([requirement_share(tr, req_year) for tr in mine], axis=0) > 0
        kinds = sorted({k for tr in mine for k, (_, nw) in tr.types.items() if nw > 0 and k in left})
        for k in kinds:
            for r in np.flatnonzero(mapped & has):
                if left[k][r] > 0 or k in open_types:
                    cols.append((s, k, int(r), -1))
            if any(tr.imports for tr in mine):
                for (a, b) in link:
                    if mapped[b] and has[b] and not mapped[a] and (left[k][a] > 0 or k in open_types):
                        cols.append((s, k, a, b))
    coef = np.zeros((len(trs), len(cols)))
    const, price, need = np.zeros(len(trs)), np.zeros(len(trs)), np.zeros(len(trs))
    for i, tr in enumerate(trs):
        share = requirement_share(tr, req_year)
        need[i] = float((share * sales_twh).sum())
        price[i] = price_cap(tr, req_year, deflator)
        for j, (s, k, a, b) in enumerate(cols):
            if s == tr.state and k in tr.types and (b < 0 or tr.imports):
                coef[i, j] = tr.types[k][1] * (1.0 if b < 0 else 1.0 - float(np.mean(links["loss"])))
        for (s, k), gen in x.items():
            if s == tr.state and k in tr.types:
                const[i] += tr.types[k][0] * float(gen[share > 0].sum())
        part = state_share(tr) * (share > 0)
        for f, (name, total) in (("chp", (tr.chp, tr.chp_total)), ("dg", (tr.dg, tr.dg_total))):
            for code, mult in name.items():
                if code in END_USE:
                    g = cogen[:, END_USE.index(code), : 2 if total else 1].sum(axis=1)
                    const[i] += mult * float((part * g).sum())
    return {"tranches": trs, "cols": cols, "coef": coef, "const": const, "price": price, "need": need, "left": left,
            "pool": pool, "used": used, "link": link, "x": x}
