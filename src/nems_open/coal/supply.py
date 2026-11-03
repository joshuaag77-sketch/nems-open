"""Coal supply curves: the pricing equation of CalculationOfCoalPricingEquation(BaseYearItr1).

Each of the 14 supply curves (SCrv1, one per region, mine type and rank) has a price equation

    SC_PRICE(q) = MULT * CUH^(RC - RC*(u/CUH)^X) * u^(RC*(u/CUH)^X) + CALK ,   u = 100 * q / FY_PROD_CAP

where CUH is the historical capacity utilization (percent), RC the utilization coefficient (RC_Util_T),
X an exponent (UtilExpBot for steps 1 to 5, UtilExpTop above) and CALK the calibration constant that makes
the base year's step-6 price equal the base-year minemouth price. Eleven steps run from -54% to +60% of the
target output (StepSize). MULT folds in productivity, wages, capital cost, fuel, capacity and other operating
cost; in the base year it is BY_MULT (coal.ams 20021).

`base_year()` is CalculationOfCoalPricingEquationBaseYearItr1 for the 14 curves: step prices (1992$/ton and
1987$/MMBtu), step quantities and capacity, from the input files and the restart's macro series.
"""

import re
from dataclasses import dataclass

import numpy as np

from nems_open.coal import inputs
from nems_open.coal.macro import Macro
from nems_open.coal.state import COAL_AMS

UTIL_EXP_BOT, UTIL_EXP_TOP = 1.5, 2.0       # coal.ams 19606-19613
CPS_BASE_YR = 2024                          # coal.ams 19592


def step_sizes() -> np.ndarray:
    """StepSize: +/- fraction of the step-6 target for each of the 11 steps (coal.ams 19641)."""
    text = COAL_AMS.read_text(encoding="latin-1")
    i = text.index("Parameter StepSize {")
    block = text[i: text.index("}", text.index("InitialData", i) + 30)]
    pairs = re.findall(r"(\d+)\s*:\s*(-?[\d.]+)", block)
    out = np.zeros(max(int(k) for k, _ in pairs))
    for k, v in pairs:
        out[int(k) - 1] = float(v)
    return out


def sc_price(mult, cuh, rc_util, q_over_cap, calk, exp):
    """SC_PRICE for output q as a share of capacity (0 to 1). Arrays broadcast over curves."""
    u = 100.0 * q_over_cap
    r = (u / cuh) ** exp
    return mult * cuh ** (rc_util - rc_util * r) * u ** (rc_util * r) + calk


@dataclass
class Curves:
    keys: list                  # (scrv1, sreg, sulf, mtyp, rank), ordered by scrv1
    v: dict                     # name -> array over curves
    mult: np.ndarray            # BY_MULT
    calk: np.ndarray            # CALK
    ppri: np.ndarray            # PPRI


def _arr(data, name, keys, default=0.0):
    p = data.param(name) if name in data.params else {}
    return np.array([float(p.get(k, default)) for k in keys])


def curves(data=None, macro=None) -> Curves:
    data, macro = data or inputs.load(), macro or Macro()
    y = CPS_BASE_YR
    keys = sorted(data.param("btu"), key=lambda k: k[0])
    A = lambda n, d=0.0: _arr(data, n, keys, d)
    at_year = lambda n, yr: np.array([float(data.param(n).get(k + (yr,), np.nan)) for k in keys])
    j92_87 = macro.deflate(1987, 1992)

    rho = A("rcoe_rho")
    rc = {
        "cont": A("rcoe_ocont") + A("rcoe_sregcont") + A("rcoe_mtypecont") + A("rcoe_sregmtypecont"),
        "tph": A("rcoe_tph") + A("rcoe_sregtph") + A("rcoe_mtypetph") + A("rcoe_sregmtypetph"),
        "prodcap": A("rcoe_prodcap") + A("rcoe_mtypeprodcap"),
        "util": A("rcoe_util") + A("rcoe_mtypeutil"),
        "fuel": A("rcoe_fuel") + A("rcoe_mtypefuel"),
        "wage": A("rcoe_wage") + A("rcoe_mtypewage"),
    }
    tph, prod_cap, cap_util = A("by_tph"), A("by_prod_cap"), A("by_cap_util")
    cuh = A("cap_util_hist")
    wage92 = A("by_wage") * j92_87
    mmp92 = A("by_mmp") * j92_87

    # Usr_Cst_Capital, MINE_FUEL and P_OPER_OTH at the base year
    p_eq, p_eq_prev = at_year("p_equip", y), at_year("p_equip", y - 1)
    ucc = ((macro.series("MC_RLRMCORPPUAA", y) / 100.0) + 0.1 - (p_eq / p_eq_prev - 1.0)) * p_eq
    d_fuel = macro.price("PDSIN", y) * j92_87
    mine_fuel = A("by_elec_price") * A("elec_share") + d_fuel * A("dist_share")
    p_oth = at_year("ppi_steel_explo", y)

    with np.errstate(all="ignore"):
        bb = np.where(tph > 0,
                      np.exp(rc["cont"] * (1 - rho)) * tph ** (A("tph_sda") * (1 - rho))
                      * A("by_prod_cap_adj") ** (rc["prodcap"] * (1 - rho)) * A("by_mmp_adj") ** (-rho)
                      * prod_cap ** (A("prodcap_sda") * (1 - rho)), 0.0)
        ur = ((cap_util * 100.0) / cuh) ** UTIL_EXP_TOP
        poper, ucap = A("rcoe_poperoth"), A("rcoe_usercstcap")
        mult = (bb * tph ** rc["tph"] * wage92 ** rc["wage"] * ucc ** ucap * mine_fuel ** rc["fuel"]
                * prod_cap ** rc["prodcap"] * p_oth ** poper * mmp92 ** rho
                * tph ** (-rho * rc["tph"]) * wage92 ** (-rho * rc["wage"]) * ucc ** (-rho * ucap)
                * mine_fuel ** (-rho * rc["fuel"]) * prod_cap ** (-rho * rc["prodcap"])
                * p_oth ** (-rho * poper)
                * (cap_util * 100.0) ** (-rho * (rc["util"] * ur))
                * cuh ** ((rc["util"] - ur * rc["util"]) * (-rho)))
        ppri = mult * (cap_util * 100.0) ** (rc["util"] * ur) * cuh ** (rc["util"] - ur * rc["util"])
    v = dict(rho=rho, cuh=cuh, rc_util=rc["util"], mmp92=mmp92, cap_util=cap_util, prod_cap=prod_cap,
             btu=A("btu"), by_prod=A("by_prod"), tph=tph, rc=rc, mine_fuel=mine_fuel, ucc=ucc, p_oth=p_oth)
    return Curves(keys, v, mult, mmp92 - ppri, ppri)


def base_year(c: Curves | None = None, data=None, macro=None) -> dict:
    """Step prices and quantities for the base year, arrays of shape (curves, 11)."""
    data, macro = data or inputs.load(), macro or Macro()
    c = c or curves(data, macro)
    v, steps, keys = c.v, step_sizes(), c.keys
    adj_add = np.array([float(data.param("adj_mmp_add").get(k + (CPS_BASE_YR,), 0.0)) for k in keys])
    adj_mul = np.array([float(data.param("adj_mmp_mult").get(k + (CPS_BASE_YR,), 1.0)) for k in keys])
    t_qtarg = v["prod_cap"] * v["cap_util"]
    t_quan = np.minimum(t_qtarg[:, None] * (1.0 + steps[None, :]), v["prod_cap"][:, None] * 0.99)
    exp = np.where(np.arange(1, len(steps) + 1) <= 5, UTIL_EXP_BOT, UTIL_EXP_TOP)[None, :]
    price = sc_price(c.mult[:, None], v["cuh"][:, None], v["rc_util"][:, None],
                     t_quan / v["prod_cap"][:, None], c.calk[:, None], exp)
    price87 = (price * macro.deflate(1992, 1987) + adj_add[:, None]) * adj_mul[:, None]
    quan = np.diff(t_quan, axis=1, prepend=0.0)
    return dict(keys=keys, t_quan=t_quan, sc_quan=quan, sc_price=price, sc_price87=price87,
                sc_1_price87=price87 / v["btu"][:, None])


# --- forecast years: the pricing procedure with lagged state seeded from the restart ----------------

class Chain:
    """CalculationOfCoalPricingEquation for 2025 onward, one year at a time.

    Substitutions for the AIMMS case-file lag state (all logged in docs/coal_lp.md):
      FY_PROD_CAP      the restart's USO2GRP/XCL_PCAP (TBtu) divided by Btu; the model's own output.
      QTarget/LAG_PROD the previous year's solved production (this chain's LP), 2024 = BY_PROD.
      LAG_PRI          the previous year's step price at the curve's production (2024 = BY_MMP92).
    """

    def __init__(self, data=None, macro=None):
        self.data = data or inputs.load()
        self.macro = macro or Macro()
        self.c = curves(self.data, self.macro)
        self.keys = self.c.keys
        v = self.c.v
        A = lambda n, d=0.0: _arr(self.data, n, self.keys, d)
        self.A = A
        self.at = lambda n, yr, d=np.nan: np.array([float(self.data.param(n).get(k + (yr,), d)) for k in self.keys])
        self.steps = step_sizes()
        self.j92_87 = self.macro.deflate(1987, 1992)
        self.state = dict(year=CPS_BASE_YR, tph=v["tph"].copy(), mine_fuel=v["mine_fuel"].copy(),
                          cap=v["prod_cap"].copy(), prod=v["by_prod"].copy(), lag_pri=v["mmp92"].copy())
        self.div = np.array([2 if k[0] <= 6 else 5 if k[0] <= 11 else 6 for k in self.keys])
        self.util = {n: A(n) for n in ("util_min", "util_mid", "util_max")}

    def _pelin(self, y):
        return np.array([self.macro.price("PELIN", y, region=int(d)) for d in self.div])

    def year(self, y: int, prod_prev: np.ndarray | None = None) -> dict:
        """Step prices and quantities for year y (> base), given production last year in tons."""
        st, v, A, mac = self.state, self.c.v, self.A, self.macro
        assert y == st["year"] + 1
        if prod_prev is not None:
            st["prod"] = prod_prev
        rho, rc, cuh = v["rho"], v["rc"], v["cuh"]
        cap = np.array(self.macro.s["USO2GRP/XCL_PCAP"][:14, y - 1990], float) / v["btu"]
        tph = st["tph"] * self.at("tph_growth_rate", y)
        wage = A("by_wage") * self.at("wage_multiplier", y) * self.j92_87
        p_eq, p_eq_prev = self.at("p_equip", y), self.at("p_equip", y - 1)
        ucc = ((mac.series("MC_RLRMCORPPUAA", y) / 100.0) + 0.1 - (p_eq / p_eq_prev - 1.0)) * p_eq
        d_new, d_old = mac.price("PDSIN", y) * self.j92_87, mac.price("PDSIN", y - 1) * self.j92_87
        es, ds = A("elec_share"), A("dist_share")
        mf = st["mine_fuel"] * (self._pelin(y) * es + d_new * ds) / (self._pelin(y - 1) * es + d_old * ds)
        p_oth = self.at("ppi_steel_explo", y)
        cap_prev = st["cap"]
        # last year's production, held between the utilization limits (T_UTIL2 logic)
        prod3 = st["prod"]
        t_util2 = prod3 / cap if y >= CPS_BASE_YR + 3 else v["cap_util"]
        lag_prod = np.where(t_util2 < v["cap_util"], cap * v["cap_util"],
                            np.where(t_util2 > self.util["util_max"], cap * self.util["util_max"], prod3))
        lag_pri = np.maximum(st["lag_pri"], 0.01)
        ulag = (lag_prod / cap_prev) * 100.0
        ur = (ulag / cuh) ** UTIL_EXP_TOP
        poper, ucap = A("rcoe_poperoth"), A("rcoe_usercstcap")
        with np.errstate(all="ignore"):
            mult = (v["rc"]["cont"] * 0 + self.c.mult / self.c.mult) * 0  # placeholder replaced below
            bb = np.where(v["tph"] > 0,
                          np.exp(rc["cont"] * (1 - rho)) * v["tph"] ** (A("tph_sda") * (1 - rho))
                          * A("by_prod_cap_adj") ** (rc["prodcap"] * (1 - rho)) * A("by_mmp_adj") ** (-rho)
                          * v["prod_cap"] ** (A("prodcap_sda") * (1 - rho)), 0.0)
            mult = (bb * tph ** rc["tph"] * wage ** rc["wage"] * ucc ** ucap * mf ** rc["fuel"]
                    * cap ** rc["prodcap"] * p_oth ** poper * lag_pri ** rho
                    * tph ** (-rho * rc["tph"]) * wage ** (-rho * rc["wage"]) * ucc ** (-rho * ucap)
                    * mf ** (-rho * rc["fuel"]) * cap ** (-rho * rc["prodcap"]) * p_oth ** (-rho * poper)
                    * ulag ** (-rho * (rc["util"] * ur))
                    * cuh ** ((rc["util"] - ur * rc["util"]) * (-rho)))
            q_target = prod3
            t_util = q_target / cap
            t_qtarg = np.where(v["cap_util"] > 0,
                               np.where(t_util < self.util["util_min"], cap * self.util["util_min"],
                                        np.where(t_util <= self.util["util_max"], q_target, cap * self.util["util_max"])), 0.0)
            t_quan = np.minimum(t_qtarg[:, None] * (1.0 + self.steps[None, :]), cap[:, None] * 0.99)
            exp = np.where(np.arange(1, len(self.steps) + 1) <= 5, UTIL_EXP_BOT, UTIL_EXP_TOP)[None, :]
            price = sc_price(mult[:, None], cuh[:, None], v["rc_util"][:, None], t_quan / cap[:, None],
                             self.c.calk[:, None], exp)
        adj_add, adj_mul = self.at("adj_mmp_add", y, 0.0), self.at("adj_mmp_mult", y, 1.0)
        price87 = (price * mac.deflate(1992, 1987) + adj_add[:, None]) * adj_mul[:, None]
        quan = np.concatenate([t_quan[:, :1], t_quan[:, 1:] * 1.00001 - t_quan[:, :-1]], axis=1)
        out = dict(year=y, cap=cap, t_quan=t_quan, sc_quan=quan, sc_price=price, sc_price87=price87,
                   sc_1_price87=price87 / v["btu"][:, None], mult=mult)
        st.update(year=y, tph=tph, mine_fuel=mf, cap=cap)
        self._last = out
        return out

    def settle(self, production_tons: np.ndarray):
        """Record the solved production for the year just priced; it becomes next year's lag state."""
        o = self._last
        self.state["prod"] = production_tons
        # step price at the curve's output (linear in cumulative quantity)
        self.state["lag_pri"] = np.array([np.interp(production_tons[i], o["t_quan"][i], o["sc_price"][i])
                                          for i in range(len(production_tons))])
