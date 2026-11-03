"""The dispatch LP as the model's electricity supply.

`run_model.run(elec="lp")` calls `ElectricityLP.solve` once per pass. It takes the demand modules'
electricity sales (the loop's current QBLK/qel* arrays), the loop's current fuel prices and a
carbon price, and returns what the rest of NEMS needs from the power sector: fuel use, power CO2
and the wholesale marginal cost of energy. Retail electricity prices still come from the stand-in
until EFP is ported.

Capacity is fixed at the reference case's path (cb2026). Only dispatch responds, so a carbon price
moves coal to gas and shifts fuel use, but it does not build or retire plants.
"""

from dataclasses import dataclass, replace

import numpy as np

from nems_open.emm import db, demand, dispatch, history
from nems_open.snapshot import Snapshot

US = 10                    # the US row of the census arrays
NUM_R = dispatch.NUM_R
CO2_PER_C = 44.0 / 12.0
PRICE_KEYS = {"coal": "MPBLK/pclel", "gas": "MPBLK/pngel", "distillate": "MPBLK/pdsel", "residual": "MPBLK/prsel"}
RATIO_CLIP = (0.2, 5.0)    # a fuel price can move by up to this factor from the reference run


@dataclass
class LPResult:
    year: int
    status: str
    power_fuel: dict               # QBLK/q*el arrays (11, 61), trillion Btu
    co2_el: np.ndarray             # (11, 61), million metric tons CO2
    wholesale: np.ndarray          # (25,) load-weighted marginal cost by EMM region, 1987$/MWh
    wholesale_us: float            # load-weighted national average, 1987$/MWh
    generation_twh: dict           # group -> (25,)
    fuel_tbtu: dict                # fuel -> (25,)
    co2_mt: float
    unserved_twh: float = 0.0      # load the fleet could not meet
    curtailed_twh: float = 0.0     # flexible load cut


def _census_of_region() -> np.ndarray:
    """Census division (0-based) of each EMM region, from the input database."""
    t = db.table("V_EMM_ECPDAT_REG_ECPT")
    out = np.zeros(NUM_R, dtype=int)
    for r, ty, c in zip(t["EMM_REG"], t["ECP_TYP"], t["EPCENSUS"]):
        if ty == 1 and r <= NUM_R:
            out[r - 1] = int(c) - 1
    return out


class ElectricityLP:
    def __init__(self, supply, hours_per_block: int = 3, added_load=None):
        if supply.baseline != "cb2026":
            raise ValueError("elec='lp' takes its capacity from the cb2026 reference run, so the baseline must be cb2026")
        self.supply = supply
        self.base = supply.base
        self.snapshot = Snapshot()
        self.hours_per_block = hours_per_block
        self.added_load = added_load          # datacenter.AddedLoad: already in the loop's commercial sales
        self._cases = {}
        self._census = _census_of_region()
        self.last: dict[int, LPResult] = {}

    def case(self, year: int) -> dispatch.DispatchCase:
        """The year's fixed inputs (capacity, heat rates, profiles, links), built once."""
        if year not in self._cases:
            self._cases[year] = dispatch.reduce_hours(dispatch.build_case(self.snapshot, year, "none"), self.hours_per_block)
        return self._cases[year]

    def _scaled_prices(self, case, prices: dict, j: int) -> dict:
        out = dict(case.price)
        for fuel, key in PRICE_KEYS.items():
            if key not in prices:
                continue
            now = prices[key][:, j][self._census]
            then = self.base[key][:, j][self._census]
            ratio = np.divide(now, then, out=np.ones(NUM_R), where=then > 0)
            out[fuel] = case.price[fuel] * np.clip(ratio, *RATIO_CLIP)
        return out

    def solve(self, year: int, q: dict, prices: dict, cp87: float = 0.0) -> LPResult:
        """Dispatch for one year. `q` and `prices` are the loop's QBLK/ and MPBLK/ arrays."""
        j = year - history.FIRST_YEAR
        case0 = self.case(year)
        net = demand.net_load_twh(self.snapshot, year, sales=q)
        extra = {}
        if self.added_load is not None and self.added_load.twh[j] > 0:
            # the added load's share of each region's net load (losses included) runs flat
            q0 = dict(q)
            q0["QBLK/qelcm"] = q["QBLK/qelcm"].copy()
            q0["QBLK/qelcm"][:9, j] = q["QBLK/qelcm"][:9, j] - self.added_load.tbtu(j)
            extra = {"flat_twh": np.maximum(net - demand.net_load_twh(self.snapshot, year, sales=q0), 0.0),
                     "flex_share": self.added_load.flex_share}
        case = replace(case0, net_load_twh=net, price=self._scaled_prices(case0, prices, j), carbon_price=float(cp87), **extra)
        res = dispatch.solve(case)
        if not res.status.startswith("ok"):
            raise RuntimeError(f"{year}: dispatch {res.status}")
        fuel = {k: float(v.sum()) for k, v in res.fuel_tbtu.items()}
        total = {"QBLK/qclel": fuel["coal"], "QBLK/qngel": fuel["gas"], "QBLK/qdsel": fuel["distillate"],
                 "QBLK/qrsel": fuel["residual"]}
        power = {}
        for name, value in total.items():
            power[name] = self._spread(q[name], self.base[name], j, value)
        # Core and non-core gas are parts of the gas total: move them with it.
        gas_factor = total["QBLK/qngel"] / self.base["QBLK/qngel"][US, j] if self.base["QBLK/qngel"][US, j] > 0 else 1.0
        for name in ("QBLK/qgfel", "QBLK/qgiel"):
            if name in self.base:
                power[name] = q[name].copy()
                power[name][:, j] = self.base[name][:, j] * gas_factor
        co2_total = float(res.co2_mt.sum())
        el = self.base["EMISSION/emelc"][:, 0, :] * CO2_PER_C
        co2_el = el.copy()
        share = np.divide(el[:, j], el[US, j], out=np.zeros(11), where=el[US, j] > 0)
        co2_el[:, j] = share * co2_total
        wholesale = res.average_price()
        out = LPResult(year, res.status, power, co2_el, wholesale,
                       float((wholesale * case.net_load_twh).sum() / case.net_load_twh.sum()),
                       res.generation_twh, res.fuel_tbtu, co2_total, float(res.unserved_twh.sum()), float(res.curtailed_twh.sum()))
        self.last[year] = out
        return out

    @staticmethod
    def _spread(current: np.ndarray, base: np.ndarray, j: int, us_total: float) -> np.ndarray:
        """`current` with year j set to the US total, split over regions as in the baseline."""
        out = current.copy()
        b = base[:, j]
        out[:, j] = b * (us_total / b[US]) if b[US] > 0 else b
        return out
