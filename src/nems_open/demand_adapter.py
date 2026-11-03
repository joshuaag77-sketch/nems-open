"""One door to the demand side for the full-model loop (run_model.py).

`DemandAdapter.solve_year(year, prices, itr)` returns that year's end-use fuel use
(QBLK names, one value per region) for a set of delivered prices (MPBLK names). Behind
it, each sector is one of:

- EIA's ported module, through the demand runner (`nems_open.run_demand`, branch
  demand-runner). Residential and commercial are ported. They start from the oracle's
  state dumps, so they are opt-in: `DemandAdapter(ported=("residential", "commercial"))`.
  A requested sector whose state is not dumped for the start year falls back to its
  stub, with a warning. Industrial is a slot that supplies its oracle's fuel use.
- A stub: EIA's reference fuel use moved by a price elasticity with a lag. Used for
  industrial and transportation (not ported yet) and, by default, for every sector so
  the loop runs in seconds. Its elasticities are fitted from EIA's side cases where
  the data allow (see ELASTICITY).

Policy levers (`Policy`) are applied here, after the sector models:
- building_efficiency multiplies residential and commercial fuel use;
- ev_share sets the plug-in share of new light-duty sales. With transportation ported,
  it acts through the vehicle choice inside TRAN (TransportationSector); with the stub,
  it moves gasoline to electricity as the fleet turns over (EVLever);
- carbon_price is a supply-side lever (the loop passes it to the supply stand-in).
"""

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from nems_open.supply_standin.data import FIRST_YEAR, NYEARS, US

SECTORS = {"residential": "rs", "commercial": "cm", "industrial": "in", "transportation": "tr"}
BUILDINGS = ("rs", "cm")

# Stub price response. Long-run own-price elasticity of each sector's fuel use, reached
# gradually: each year closes ADJUSTMENT[sector] of the gap (a Koyck lag). Fitted per
# sector and fuel from EIA's AEO2026 side cases (fit_elasticities.py,
# docs/demand_elasticities.md); fuels without a usable fit keep the sector's
# placeholder (PLACEHOLDER).
PLACEHOLDER = {"rs": -0.30, "cm": -0.30, "in": -0.30, "tr": -0.20}
_FITTED = json.loads(Path(__file__).with_name("demand_elasticities.json").read_text())
ADJUSTMENT = {s: v["adjustment"] for s, v in _FITTED.items()}
ELASTICITY = {(s, f): v["used"] for s, fit in _FITTED.items() for f, v in fit["fuels"].items()}


def elasticity(sector: str, fuel: str) -> float:
    fuel = "ng" if fuel in CORE_NONCORE else fuel
    return ELASTICITY.get((sector, fuel), PLACEHOLDER[sector])

# Fleet turnover for the EV lever: the fleet's plug-in share closes 1/VEHICLE_LIFE of
# the gap to the sales share each year.
VEHICLE_LIFE = 15
PLUG_IN = [3, 4, 5, 6, 14]  # TRANREP technology rows: EV100, PHEV20, PHEV50, EV200, EV300
TRQLDV_GASOLINE, TRQLDV_ELECTRICITY = 0, 5

# Rows that are sums of other rows: recomputed, never moved on their own.
TOTAL_FUELS = ("tp", "tr", "ts")
CORE_NONCORE = ("gf", "gi")  # parts of natural gas (ng)
PETROLEUM = ("mg", "ds", "ks", "lg", "rs", "rl", "rh", "jf", "pf", "as", "ot", "pc", "sg", "lp", "ci")
RENEWABLE = ("bm", "st", "pv", "ge", "wi", "hy", "et")


def by_year(value, start_year: int, default: float) -> np.ndarray:
    """A lever as one value per year 1990-2050: a number applies from start_year on."""
    out = np.full(NYEARS, default, dtype=np.float64)
    a = np.asarray(value, dtype=np.float64)
    if a.ndim == 0:
        out[start_year - FIRST_YEAR:] = a
    else:
        out[:] = a
    return out


@dataclass
class Policy:
    carbon_price: object = 0.0          # 2024 $ per metric ton CO2, number or (61,) by year
    ev_share: object = None             # plug-in share of new light-duty sales, 0-1; None = EIA's
    building_efficiency: object = 1.0   # multiplier on residential and commercial fuel use
    start_year: int = 2027

    def carbon(self) -> np.ndarray:
        return by_year(self.carbon_price, self.start_year, 0.0)

    def efficiency(self) -> np.ndarray:
        return by_year(self.building_efficiency, self.start_year, 1.0)


def fuel_of(name: str) -> str:
    return name[6:8]


class StubSector:
    """Reference fuel use moved by a lagged price elasticity."""

    def __init__(self, suffix: str, base: dict):
        self.suffix = suffix
        self.base = base
        self.names = [k for k in base if k.startswith("QBLK/q") and k.endswith(suffix)
                      and len(k) == 10 and fuel_of(k) not in TOTAL_FUELS]
        self.lag = {k: np.zeros(11) for k in self.names}  # lagged dlog relative price
        self._pending = {}

    def price_name(self, qname: str) -> str | None:
        f = fuel_of(qname)
        p = f"MPBLK/p{'ng' if f in CORE_NONCORE else f}{self.suffix}"
        return p if p in self.base else None

    def solve(self, j: int, prices: dict, shifts: dict) -> dict[str, np.ndarray]:
        k_adj = ADJUSTMENT[self.suffix]
        out = {}
        for k in self.names:
            q = self.base[k][:, j] + shifts.get(k, 0.0)
            p = self.price_name(k)
            if p is not None:
                ref, now = self.base[p][:, j], prices[p][:, j]
                ok = (ref > 0) & (now > 0)
                dlog = np.where(ok, np.log(np.where(ok, now, 1.0) / np.where(ok, ref, 1.0)), 0.0)
                lag = (1 - k_adj) * self.lag[k] + k_adj * dlog
                self._pending[k] = lag
                q = q * np.exp(elasticity(self.suffix, fuel_of(k)) * lag)
            out[k] = q
        return out

    def end_year(self):
        self.lag.update(self._pending)
        self._pending = {}


def usable_ported(ported: tuple[str, ...], start_year: int) -> tuple[str, ...]:
    """The requested ported sectors whose oracle state exists for start_year; the rest fall
    back to their stubs (with a warning), so a run never fails for a missing dump."""
    if not ported:
        return ()
    from nems_open.run_demand import SECTORS as PORTS
    usable = tuple(s for s in ported if PORTS.get(s) is not None and PORTS[s].available(start_year))
    dropped = [s for s in ported if s not in usable]
    if dropped:
        warnings.warn(f"no oracle state for {', '.join(dropped)} in {start_year}; using the stub", stacklevel=3)
    return usable


class PortedSectors:
    """EIA's ported modules through the demand runner (branch demand-runner)."""

    def __init__(self, start_year: int, sectors: tuple[str, ...], base: dict, ev_share: dict | None = None):
        from nems_open.run_demand import EQUIVALENCED, SECTOR_QUANTITIES, DemandRunner, sum_quantities
        self._equivalenced = EQUIVALENCED
        self._names = SECTOR_QUANTITIES
        self._sum = sum_quantities
        self.runner = DemandRunner(start_year, sectors=sectors, ev_share=ev_share)
        self.inputs = self.runner.inputs
        self.base = base
        self.suffixes = [SECTORS[s] for s in sectors]

    def _set_prices(self, prices: dict) -> None:
        """What the demand modules read (AMPBLK, AEUSPRC) moved by the same ratio as our
        MPBLK prices against the baseline. End-use electricity prices follow pelrs/pelcm."""
        ratio = {}
        for name, p in prices.items():
            ref = self.base[name]
            ratio[name.split("/")[1]] = np.divide(p, ref, out=np.ones_like(p), where=ref != 0)
        snap = self.inputs.snapshot
        for var, full in self.inputs.by_var.items():
            block = full.split("/")[0]
            if block == "AMPBLK" and var in ratio:
                self.inputs.overrides[full] = snap[full] * ratio[var].astype(np.float32)
        for eq, parts in self._equivalenced.items():
            r = ratio["pelrs" if eq == "pelrsout" else "pelcm"]
            for part in parts:
                full = self.inputs.by_var[part]
                ref = snap[full]
                self.inputs.overrides[full] = ref * r[:, :ref.shape[1]].astype(np.float32)

    def solve(self, year: int, prices: dict, itr: int) -> dict[str, np.ndarray]:
        self._set_prices(prices)
        run = self.runner
        y = year - FIRST_YEAR + 1
        for sector, state in run.sectors:
            sector.iteration(state, year, run.first_iteration + itr - 1, run.inputs)
        calshr = lambda name: run.inputs.snapshot[f"CALSHR/{name}"]
        out = {}
        for sector, state in run.sectors:
            for k, v in sector.quantities(state).items():
                run.q[k][:9, y - 1] = v[1:9, y]  # FArray: Fortran bounds, inclusive
            self._sum(run.q, sector.suffix, y, calshr)
            for k in self._names[sector.suffix]:
                if f"QBLK/{k}" in self.base:  # qprrs and qprcm live in QMORE
                    out[f"QBLK/{k}"] = run.q[k][:, y - 1].astype(np.float64)
        return out

    def end_year(self):
        self.runner.year += 1
        self.runner.first_iteration = 1


class DemandAdapter:
    def __init__(self, base: dict, policy: Policy, start_year: int, ported: tuple[str, ...] = ()):
        self.base = base
        self.policy = policy
        ported = usable_ported(ported, start_year)
        ev_by_year = None
        if policy.ev_share is not None and "transportation" in ported:
            target = by_year(policy.ev_share, policy.start_year, np.nan)
            ev_by_year = {FIRST_YEAR + j: float(v) for j, v in enumerate(target) if not np.isnan(v)}
        self.ported = PortedSectors(start_year, ported, base, ev_by_year) if ported else None
        ported_sfx = {SECTORS[s] for s in ported}
        self.stubs = {sfx: StubSector(sfx, base) for sfx in SECTORS.values() if sfx not in ported_sfx}
        self.efficiency = policy.efficiency()
        # The stub lever only when transportation is a stub: the port has the real one.
        self._ev = EVLever(base, policy) if policy.ev_share is not None and "tr" in self.stubs else None

    @property
    def routines(self) -> list[str]:
        names = [n for n, s in SECTORS.items() if s not in self.stubs]
        return names + [f"{n} (stub)" for n, s in SECTORS.items() if s in self.stubs]

    def solve_year(self, year: int, prices: dict, itr: int) -> dict[str, np.ndarray]:
        j = year - FIRST_YEAR
        shifts = self._ev.shifts(j) if self._ev else {}
        out, keep_regions = {}, set()
        if self.ported:
            got = self.ported.solve(year, prices, itr)
            keep_regions = set(got)  # the runner already set their US and California rows
            for k, v in got.items():  # EV shifts land on transport, never on a ported building
                out[k] = v + shifts.get(k, 0.0)
        for stub in self.stubs.values():
            out.update(stub.solve(j, prices, shifts))
        eff = self.efficiency[j]
        if eff != 1.0:
            for k in out:
                if k[-2:] in BUILDINGS and fuel_of(k) not in TOTAL_FUELS:
                    out[k] = out[k] * eff
        self._totals(out, j, keep_regions)
        return out

    def _totals(self, q: dict, j: int, keep_regions=frozenset()) -> None:
        """US row as the sum of divisions; petroleum, renewable and total rows rebuilt from
        the change in their parts (so rows the models do not report keep EIA's values)."""
        for k, v in q.items():
            if fuel_of(k) in TOTAL_FUELS or k in keep_regions:
                continue
            ref = self.base[k][:, j]
            pacific = np.divide(v[8], ref[8], out=np.array(1.0), where=ref[8] != 0)
            v[9] = ref[9] * pacific
            v[US] = v[:9].sum()
        for sfx in SECTORS.values():
            delta = {k: q[k] - self.base[k][:, j] for k in q if k.endswith(sfx)
                     and fuel_of(k) not in TOTAL_FUELS + CORE_NONCORE}
            for total, members in (("tp", PETROLEUM), ("tr", RENEWABLE), ("ts", None)):
                name = f"QBLK/q{total}{sfx}"
                if name not in self.base:
                    continue
                d = sum((v for k, v in delta.items() if members is None or fuel_of(k) in members), np.zeros(11))
                q[name] = self.base[name][:, j] + d

    def end_year(self) -> None:
        if self.ported:
            self.ported.end_year()
        for stub in self.stubs.values():
            stub.end_year()


class EVLever:
    """Plug-in share of new light-duty sales -> gasoline to electricity in transport."""

    def __init__(self, base: dict, policy: Policy):
        sales = base["TRANREP/trldsalc"][:, US] + base["TRANREP/trldsalt"][:, US]
        stock = base["TRANREP/trldstkc"][:16] + base["TRANREP/trldstkt"][:16]
        self.sales_share = sales[PLUG_IN].sum(0) / np.maximum(sales.sum(0), 1e-9)
        self.fleet_share = stock[PLUG_IN].sum(0) / np.maximum(stock.sum(0), 1e-9)
        target = by_year(policy.ev_share, policy.start_year, np.nan)
        target = np.where(np.isnan(target), self.sales_share, target)
        d_sales = np.clip(target, 0, 1) - self.sales_share
        self.d_fleet = np.zeros(NYEARS)
        for j in range(1, NYEARS):
            self.d_fleet[j] = self.d_fleet[j - 1] + (d_sales[j] - self.d_fleet[j - 1]) / VEHICLE_LIFE
        q = base["TRANREP/trqldv"]
        self.gasoline, self.electricity = q[TRQLDV_GASOLINE], q[TRQLDV_ELECTRICITY]
        # Electricity per plug-in vs gasoline per other vehicle, from EIA's own fleet.
        ev = np.maximum(stock[PLUG_IN].sum(0), 1e-9)
        other = np.maximum(stock.sum(0) - stock[PLUG_IN].sum(0), 1e-9)
        self.btu_ratio = (self.electricity[US] / ev) / np.maximum(self.gasoline[US] / other, 1e-9)

    def shifts(self, j: int) -> dict[str, np.ndarray]:
        df = self.d_fleet[j]
        if df == 0:
            return {}
        gas = self.gasoline[:, j]
        cut = gas * df / max(1 - self.fleet_share[j], 1e-6)
        cut = np.clip(cut, -gas * 10, gas)  # never more gasoline removed than the LDVs burn
        return {"QBLK/qmgtr": -cut, "QBLK/qeltr": cut * self.btu_ratio[j]}
