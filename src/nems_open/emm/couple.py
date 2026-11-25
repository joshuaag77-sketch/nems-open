"""The dispatch LP as the model's electricity supply.

`run_model.run(elec="lp")` calls `ElectricityLP.solve` once per pass. It takes the demand modules'
electricity sales (the loop's current QBLK/qel* arrays), the loop's current fuel prices and a
carbon price, and returns what the rest of NEMS needs from the power sector: fuel use, power CO2
and the wholesale marginal cost of energy. Retail electricity prices still come from the stand-in
until EFP is ported.

Capacity follows the reference case's path (cb2026) by default. Only dispatch responds, so a carbon price
moves coal to gas and shifts fuel use, but it does not build or retire plants. With capacity="lp" each
year's fleet comes from the capacity expansion LP (nems_open.emm.capacity.CapacityPath), solved once per year
on the loop's own electricity demand, fuel prices and carbon price, so plants are built and retired in
response to them.
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
PACIFIC = 8                # census division of Alaska and Hawaii (0-based)
# Alaska and Hawaii. util.f adds their power-sector fuel to the Pacific division's QCLEL, QDSEL, QRSEL and QNGEL
# (6011-6038, 6385-6402) and EFD's carbon totals hold them (EMELC is UTCO2 plus EDSPOAK and EDSPOHI). The dispatch
# covers the 25 EMM regions only. On: their fuel (demand.noncontiguous_fuel_tbtu, the reference run's) and its CO2 are
# added to the loop's totals and held in the Pacific division; the rest of each total is spread as in the baseline.
# Off: the US totals leave them out and the Pacific division takes its baseline share of that (Codex finding 7).
NONCONTIGUOUS = True
# The fleet's make-up follows its capacity. A case's heat rates, VOM, heat-rate tiers, coal and cofire shares and the
# new-CC share under EPA 111 are built from the existing / new split of its capacity (dispatch.build_case). EFD builds
# them from the units the run has (udat.f: each plant group's UG_HTRT and W_CF from its own units, 6446-6447,
# 7249-7263). On: when the fleet is not the reference run's (capacity="lp" or a lever), the case is rebuilt on it.
# Off: the reference case's make-up with the new capacity put in (Codex finding 3).
COMPOSITION_FOLLOWS_CAPACITY = True


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
    def __init__(self, supply, hours_per_block: int = 3, capacity_scale=None, added_load=None,
                 capacity: str = "eia", start_year: int = 2027):
        if supply.baseline != "cb2026":
            raise ValueError("elec='lp' takes its capacity from the cb2026 reference run, so the baseline must be cb2026")
        self.supply = supply
        self.base = supply.base
        self.snapshot = Snapshot()
        self.hours_per_block = hours_per_block
        self.added_load = added_load          # datacenter.AddedLoad: already in the loop's commercial sales
        self.capacity_scale = capacity_scale   # year -> {group: multiplier}, from a lever (nems_open.levers)
        # The carbon adder inside each power fuel price (11, 61), kept by the loop with the price's own relaxation.
        self.carbon_in = {key: np.zeros((11, 61)) for key in PRICE_KEYS.values()}
        self._cases = {}
        self._fleet_cases = {}
        self._census = _census_of_region()
        self.last: dict[int, LPResult] = {}
        if capacity not in ("eia", "lp"):
            raise ValueError("capacity must be 'eia' or 'lp'")
        self.capacity_path = None
        if capacity == "lp":
            from nems_open.emm.capacity import CapacityPath
            self.capacity_path = CapacityPath(self.snapshot, start_year)

    def case(self, year: int) -> dispatch.DispatchCase:
        """The year's fixed inputs (capacity, heat rates, profiles, links), built once."""
        if year not in self._cases:
            self._cases[year] = dispatch.reduce_hours(dispatch.build_case(self.snapshot, year, "none"), self.hours_per_block)
        return self._cases[year]

    def fleet_case(self, year: int, capacity: dict) -> dispatch.DispatchCase:
        """The year's case rebuilt on `capacity` (COMPOSITION_FOLLOWS_CAPACITY), built once per year: the capacity
        path solves a year once and a lever's scale is fixed."""
        if year not in self._fleet_cases:
            builds = self.capacity_path.renewable_builds() if self.capacity_path is not None else None
            full = dispatch.build_case(self.snapshot, year, "none", capacity=capacity, builds=builds)
            self._fleet_cases[year] = dispatch.reduce_hours(full, self.hours_per_block)
        return self._fleet_cases[year]

    def _scaled_prices(self, case, prices: dict, j: int) -> dict:
        """The case's fuel prices moved by the loop's, net of the carbon adders the loop's prices hold (carbon_in):
        dispatch and the capacity LP charge carbon on each plant's own emissions (case.carbon_price)."""
        out = dict(case.price)
        for fuel, key in PRICE_KEYS.items():
            if key not in prices:
                continue
            now = prices[key][:, j][self._census]
            if key in self.carbon_in:
                now = np.maximum(now - self.carbon_in[key][:, j][self._census], 0.0)
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
        scale = self.capacity_scale(year) if self.capacity_scale else {}
        fleet = case0.capacity
        if self.capacity_path is not None:
            fleet = self.capacity_fleet(year, net, prices, j, cp87)
            extra["credit_share"] = self.capacity_path.credit_share(year)    # the path's own CCS cohorts
        capacity = {g: v * scale.get(g, 1.0) for g, v in fleet.items()}
        if COMPOSITION_FOLLOWS_CAPACITY and (self.capacity_path is not None or scale):
            case0 = self.fleet_case(year, capacity)
        case = replace(case0, capacity=capacity, net_load_twh=net, price=self._scaled_prices(case0, prices, j),
                       carbon_price=float(cp87), **extra)
        res = dispatch.solve(case)
        if not res.status.startswith("ok"):
            raise RuntimeError(f"{year}: dispatch {res.status}")
        fuel = {k: float(v.sum()) for k, v in res.fuel_tbtu.items()}
        # The electric power sector's CHP units supply part of the load outside the fleet (demand.net_load_twh); their
        # fuel is still power-sector fuel in QCLEL / QNGEL, at the reference run's level. Their oil goes to residual.
        nt = demand.nontraditional_cogen_fuel_tbtu(self.snapshot, year)
        total = {"QBLK/qclel": fuel["coal"] + nt["coal"], "QBLK/qngel": fuel["gas"] + nt["gas"],
                 "QBLK/qdsel": fuel["distillate"], "QBLK/qrsel": fuel["residual"] + nt["oil"]}
        nt_co2 = demand.nontraditional_cogen_co2_mt(self.snapshot, year)
        fixed = {name: 0.0 for name in total}
        if NONCONTIGUOUS:
            ah = demand.noncontiguous_fuel_tbtu(self.snapshot, year)
            fixed = {"QBLK/qclel": ah["coal"], "QBLK/qngel": ah["gas"], "QBLK/qdsel": ah["distillate"], "QBLK/qrsel": ah["residual"]}
            total = {name: value + fixed[name] for name, value in total.items()}
            nt_co2 += sum(ah[k] * dispatch.CO2_PER_TBTU[k] for k in ("coal", "distillate", "residual", "gas"))
        power = {}
        for name, value in total.items():
            power[name] = self._spread(q[name], self.base[name], j, value, fixed[name])
        # Core and non-core gas are parts of the gas total: move them with it.
        gas_factor = total["QBLK/qngel"] / self.base["QBLK/qngel"][US, j] if self.base["QBLK/qngel"][US, j] > 0 else 1.0
        for name in ("QBLK/qgfel", "QBLK/qgiel"):
            if name in self.base:
                power[name] = q[name].copy()
                power[name][:, j] = self.base[name][:, j] * gas_factor
        co2_total = float(res.co2_mt.sum()) + nt_co2
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

    def capacity_fleet(self, year: int, net: np.ndarray, prices: dict, j: int, cp87: float) -> dict:
        """The capacity LP's fleet for `year`, in dispatch groups. Solved once per year, the first time the loop
        asks, on that pass's demand, fuel prices and carbon price; later passes reuse it (ECP runs on iteration 1)."""
        from nems_open.emm import capacity as cap
        if year not in self.capacity_path.results:
            full = dispatch.build_case(self.snapshot, year, "none")
            full = replace(full, net_load_twh=net, price=self._scaled_prices(full, prices, j), carbon_price=float(cp87))
            self.capacity_path.step(year, full)
        return cap.dispatch_capacity(self.capacity_path.results[year].capacity)

    @staticmethod
    def _spread(current: np.ndarray, base: np.ndarray, j: int, us_total: float, pacific_fixed: float = 0.0) -> np.ndarray:
        """`current` with year j set to the US total, split over regions as in the baseline. `pacific_fixed` (Alaska
        and Hawaii) is held in the Pacific division and only the rest is split."""
        out = current.copy()
        f = np.zeros(len(base))
        f[PACIFIC] = f[US] = pacific_fixed
        b = base[:, j] - f
        rest = us_total - pacific_fixed
        out[:, j] = (b * (rest / b[US]) if b[US] > 0 else b) + f
        return out
