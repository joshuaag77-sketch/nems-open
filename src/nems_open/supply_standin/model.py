"""The stand-in supply side: demand in, delivered prices and CO2 out.

Every price is the baseline case's price moved by fitted log-log responses:

    P = (P_base + crude) * exp(a * dlog Q_fuel + c * dlog P_gas_to_power)

where dlog X = log(X / X_base) and `crude` is the change in Brent passed through dollar
for dollar to refined products (zero for electricity, gas, coal, propane). With baseline demand and Brent it returns the
baseline's prices exactly. The coefficients come from `fit.py`, fitted across EIA's
AEO2026 side cases, and live in `coefficients.json`.

Inputs and outputs use restart-file names and shapes: QBLK/q<fuel><sector> and
MPBLK/p<fuel><sector>, each (11 regions, 61 years 1990-2050), region 10 = US.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from nems_open.supply_standin.data import FIRST_YEAR, US, load_case

COEFFICIENTS = Path(__file__).with_name("coefficients.json")

DEMAND_SECTORS = ("rs", "cm", "in", "tr")
EMISSION_SECTORS = {  # sector -> EIA's carbon-by-region array (pollutant 0 = carbon)
    "rs": "EMISSION/emrsc", "cm": "EMISSION/emcmc", "in": "EMISSION/emincc",
    "tr": "EMISSION/emtrc", "el": "EMISSION/emelc",
}
CO2_PER_C = 44.0 / 12.0
DOLLAR_YEAR = 2024  # carbon prices come in 2024 dollars per metric ton CO2

# Fuel code -> (fitting group, the total-demand quantity that drives its price).
# Electricity is regional (each census division's own sales); the rest are national
# markets, driven by the US total.
DRIVERS = {
    "el": ("el", "QBLK/qelas"),
    "ng": ("ng", "QBLK/qngas"), "gf": ("ng", "QBLK/qngas"), "gi": ("ng", "QBLK/qngas"),
    "ds": ("oil", "QBLK/qdsas"), "mg": ("oil", "QBLK/qmgas"), "jf": ("oil", "QBLK/qjftr"),
    "lg": ("ngl", "QBLK/qlgas"), "ks": ("oil", "QBLK/qksas"), "rl": ("oil", "QBLK/qrlas"),
    "rh": ("oil", "QBLK/qrhas"), "rs": ("oil", "QBLK/qrsas"), "ot": ("oil", "QBLK/qotas"),
    "pf": ("oil", "QBLK/qpfin"), "as": ("oil", "QBLK/qasin"), "et": ("oil", "QBLK/qettr"),
    "tp": ("oil", "QBLK/qtpas"), "lp": ("oil", "QBLK/qlpin"),
    "cl": ("coal", "QBLK/qclas"), "mc": ("coal", "QBLK/qmcin"),
}
REGRESSORS = {"el": ("q", "pngel"), "ng": ("q",), "oil": ("q",), "ngl": ("q",), "coal": ("q",)}
# Crude passes through to refined products dollar for dollar: a $1/bbl move in Brent moves
# a product's price by $1 per barrel of product, i.e. 1/(MMBtu per barrel) per MMBtu.
# EIA's standard heat contents. Propane (a gas-plant liquid) and ethanol do not follow crude.
CRUDE_PASS_THROUGH = 1.0
MMBTU_PER_BBL = {"mg": 5.053, "ds": 5.774, "jf": 5.670, "ks": 5.670, "rl": 6.287, "rh": 6.287,
                 "rs": 6.287, "ot": 5.825, "pf": 5.248, "as": 6.636, "tp": 5.400, "lp": 5.825}
REGIONAL = {"el"}
SWITCH_ROUNDS = 50
SWITCH_TOL = 1e-5  # relative change in power-plant fuel burn between rounds
SWITCH_CLIP = 3.0  # a fuel's effective cost can rise up to e^3 (20x) before the curve stops
DLOG_CLIP = 1.0  # |dlog| capped at 1 (a factor of e) so a zeroed fuel cannot blow up a price


def parse_price(name: str) -> tuple[str, str]:
    """MPBLK/pngrs -> ("ng", "rs")."""
    body = name.split("/", 1)[1][1:]
    return body[:2], body[2:]


def dlog(new, base):
    new = np.asarray(new, dtype=np.float64)
    base = np.asarray(base, dtype=np.float64)
    ok = (new > 0) & (base > 0)
    out = np.zeros(np.broadcast(new, base).shape)
    np.log(np.where(ok, new, 1.0) / np.where(ok, base, 1.0), out=out, where=ok)
    return np.clip(out, -DLOG_CLIP, DLOG_CLIP)


def regressors(fuel: str, totals: dict, base: dict, brent, pngel) -> dict[str, np.ndarray]:
    """The (11, 61) regressors for one fuel's prices, as deviations from the baseline."""
    group, qname = DRIVERS[fuel]
    dq = dlog(totals[qname], base[qname])
    if group not in REGIONAL:
        dq = np.broadcast_to(dq[US], dq.shape)
    x = {"q": dq}
    if "pngel" in REGRESSORS[group]:
        x["pngel"] = dlog(pngel, base["MPBLK/pngel"])
    return x


def crude_shift(fuel: str, brent, base: dict) -> np.ndarray | float:
    """Level change in a product's price (1987 $/MMBtu, by year) from the change in Brent."""
    if fuel not in MMBTU_PER_BBL:
        return 0.0
    return CRUDE_PASS_THROUGH * (brent - base["INTOUT/brent_price"]) / MMBTU_PER_BBL[fuel]


def crude_adjusted(name: str, brent, base: dict) -> np.ndarray:
    """The baseline price after the crude pass-through, never below 1% of the baseline."""
    p = base[name]
    return np.maximum(p + crude_shift(parse_price(name)[0], brent, base), np.minimum(0.01 * p, p))


def carbon_factor(base: dict, fuel: str, sector: str):
    """Metric tons CO2 per MMBtu, by year, from EIA's carbon factors (kg C per MMBtu)."""
    name = f"EMEBLK/e{fuel}{sector}"
    if name not in base:
        same_fuel = sorted(k for k in base if k.startswith(f"EMEBLK/e{fuel}") and len(k) == 12)
        if not same_fuel:
            return None
        name = same_fuel[0]
    return base[name] * CO2_PER_C / 1000.0


@dataclass
class Result:
    prices: dict[str, np.ndarray]           # MPBLK/p*, 1987 $/MMBtu, (11, 61)
    power_fuel: dict[str, np.ndarray]       # QBLK/q*el, trillion Btu, (11, 61)
    co2: dict[str, np.ndarray]              # sector -> million metric tons CO2, (11, 61)
    totals: dict[str, np.ndarray]           # QBLK/q*as and other driver totals after the response
    carbon_adders: dict[str, np.ndarray] = field(default_factory=dict)  # 1987 $/MMBtu

    @property
    def co2_total(self) -> np.ndarray:
        """US energy CO2 by year, million metric tons (sum of the five sectors)."""
        return sum(v[US] for v in self.co2.values())


class SupplyStandin:
    def __init__(self, baseline: str = "cb2026", coefficients: Path = COEFFICIENTS):
        self.baseline = baseline
        self.base = load_case(baseline)
        coef = json.loads(Path(coefficients).read_text())
        self.price_coef = {k: v["coef"] for k, v in coef["prices"].items()}
        self.power_mix = coef["power_mix"]
        self.switching = coef.get("power_switching")
        self._accounting = self._accounting_pairs()
        self._calibration = {s: self._calibrate(s) for s in EMISSION_SECTORS}

    # Quantities ------------------------------------------------------------

    def _demand(self, demand: dict) -> dict[str, np.ndarray]:
        """End-use demand, baseline values wherever the caller gave none."""
        q = {}
        for k, v in self.base.items():
            if k.startswith("QBLK/q") and k[-2:] in DEMAND_SECTORS:
                q[k] = np.asarray(demand.get(k, v), dtype=np.float64)
        return q

    def _power_fuel(self, d_elec_us: np.ndarray) -> dict[str, np.ndarray]:
        """Power-sector fuel use: the baseline plus each fuel's fitted share of the change
        in US electricity sales, spread over regions by the baseline's regional split."""
        out = {}
        for name, m in self.power_mix.items():
            b = self.base[name]
            share = np.divide(b, b[US], out=np.zeros_like(b), where=b[US] > 0)
            out[name] = np.maximum(b + share * (m * d_elec_us), np.minimum(b, 0.0))
        return out

    def _totals(self, q: dict, power: dict) -> dict[str, np.ndarray]:
        """Driver totals: baseline total plus the change in each sector that uses the fuel."""
        totals = {}
        for _, qname in DRIVERS.values():
            if qname in totals or qname not in self.base:
                continue
            fuel = qname[6:8]
            t = self.base[qname].copy()
            for s in DEMAND_SECTORS:
                k = f"QBLK/q{fuel}{s}"
                if k in q and k != qname:
                    t += q[k] - self.base[k]
            k = f"QBLK/q{fuel}el"
            if k in power and k != qname:
                t += power[k] - self.base[k]
            if qname[-2:] in DEMAND_SECTORS:  # the driver is itself a single sector (qjftr, qpfin)
                t = q[qname].copy()
            totals[qname] = t
        return totals

    # Prices ----------------------------------------------------------------

    def _prices(self, totals: dict, brent) -> dict[str, np.ndarray]:
        """Every MPBLK price before carbon adders."""
        base = self.base
        prices = {}
        names = sorted(k for k in base if k.startswith("MPBLK/p"))
        # Gas first: electricity prices respond to the price of gas to power plants.
        for name in sorted(names, key=lambda n: parse_price(n)[0] == "el"):
            fuel, _ = parse_price(name)
            if fuel not in DRIVERS:
                prices[name] = base[name].copy()
                continue
            x = regressors(fuel, totals, base, brent, prices.get("MPBLK/pngel"))
            prices[name] = self._move(name, x, brent)
        return prices

    # Power-sector fuel switching ------------------------------------------------

    def _cp87(self, carbon_price) -> np.ndarray:
        """Carbon price in 1987 $ per metric ton CO2, by year."""
        if carbon_price is None:
            return np.zeros(61)
        deflator = self.base["MACOUT/mc_jpgdp"]  # index 0 is 1987
        cp = np.broadcast_to(np.asarray(carbon_price, dtype=np.float64), (61,))
        return cp / (deflator[DOLLAR_YEAR - 1987] / deflator[0])

    def _switch(self, power0: dict, prices: dict, cp87: np.ndarray) -> dict[str, np.ndarray]:
        """Gas and coal burn in power plants moved by their effective fuel cost (delivered
        price plus carbon cost) against the baseline: log Q = log Q0 + a * dlog cost.
        Coefficients from fit.fit_power_switching; the change goes to (or comes from)
        zero-carbon generation, since electricity sales are held."""
        sw = self.switching
        if not sw:
            return power0
        b = self.base
        cost = {}
        for fuel, pname, ename in (("ng", "MPBLK/pngel", "EMEBLK/engel"), ("cl", "MPBLK/pclel", "EMEBLK/eclel")):
            p, p0 = prices[pname][US], b[pname][US]
            adder = cp87 * b[ename] * CO2_PER_C / 1000.0
            ok = (p0 > 0) & (p + adder > 0)
            cost[fuel] = np.clip(np.log(np.where(ok, p + adder, 1.0) / np.where(ok, p0, 1.0)), -SWITCH_CLIP, SWITCH_CLIP)
        g0, c0 = b["QBLK/qngel"][US], b["QBLK/qclel"][US]
        # Symmetric cross effect: the gas burned per unit change in coal cost equals the
        # coal burned per unit change in gas cost, in Btu (so a_gc * Qgas = a_cg * Qcoal).
        a_gc = sw["coal_from_gas_cost"] * np.divide(c0, g0, out=np.zeros(61), where=g0 > 0)
        gas = np.exp(sw["gas_own"] * cost["ng"] + a_gc * cost["cl"])
        coal = np.exp(sw["coal_from_gas_cost"] * cost["ng"] + sw["coal_own"] * cost["cl"])
        out = dict(power0)
        for name in ("QBLK/qngel", "QBLK/qgfel", "QBLK/qgiel"):
            if name in out:
                out[name] = power0[name] * gas
        out["QBLK/qclel"] = power0["QBLK/qclel"] * coal
        return out

    def _move(self, name: str, x: dict, brent) -> np.ndarray:
        coef = self.price_coef.get(name)
        base = crude_adjusted(name, brent, self.base)
        if not coef:
            return base.copy()
        z = sum(c * x[k] for k, c in coef.items())
        return base * np.exp(z)

    # Emissions -------------------------------------------------------------

    def _accounting_pairs(self):
        pairs = {s: [] for s in EMISSION_SECTORS}
        for s in EMISSION_SECTORS:
            for k in self.base:
                if k.startswith("EMEBLK/e") and len(k) == 12 and k.endswith(s):
                    f = k[8:10]
                    if f in ("gf", "gi"):  # core and noncore gas are parts of ng
                        continue
                    if f"QBLK/q{f}{s}" in self.base:
                        pairs[s].append(f)
        return pairs

    def _carbon(self, s: str, q: dict) -> np.ndarray:
        """Fuel use times EIA's carbon factor, million metric tons carbon, (11, 61)."""
        total = np.zeros_like(self.base["QBLK/qelas"])
        for f in self._accounting[s]:
            total += q[f"QBLK/q{f}{s}"] * self.base[f"EMEBLK/e{f}{s}"] / 1000.0
        return total

    def _calibrate(self, s: str) -> np.ndarray:
        """EIA's reported carbon over our fuel-times-factor accounting, baseline case.
        Absorbs what the accounting misses (CCS capture, feedstocks, bunker fuels)."""
        eia = self.base[EMISSION_SECTORS[s]][:, 0, :]
        ours = self._carbon(s, self.base)
        return np.divide(eia, ours, out=np.ones_like(ours), where=ours > 0)

    # The call --------------------------------------------------------------

    def solve(self, demand: dict | None = None, brent=None, carbon_price=None,
              power_fuel: dict | None = None, co2_el: np.ndarray | None = None) -> Result:
        """Prices and emissions for one set of end-use demands.

        demand: QBLK-style arrays for the residential, commercial, industrial and
            transportation sectors (e.g. "QBLK/qelrs"), trillion Btu, (11, 61). Missing
            entries keep the baseline. Power-sector and all-sector entries are ignored:
            the stand-in computes those, unless power_fuel is given.
        brent: Brent crude price by year, 1987 $/bbl like INTOUT/brent_price, (61,).
            Default: the baseline's.
        carbon_price: 2024 $ per metric ton CO2, scalar or by year (61,). Added to every
            delivered fossil price by its carbon content, and to electricity by the power
            sector's average CO2 per unit sold.
        power_fuel: QBLK/q*el arrays (11, 61) from a better electricity model. They replace the
            stand-in's power-sector fuel use and its fuel switching; fuels not listed keep the
            stand-in's value. Gas and coal prices then respond to that fuel use.
        co2_el: power-sector CO2 (11, 61), million metric tons, replacing the stand-in's own.
        """
        base = self.base
        q = self._demand(demand or {})
        d_elec_us = sum(q[f"QBLK/qel{s}"][US] - base[f"QBLK/qel{s}"][US] for s in DEMAND_SECTORS)
        brent = base["INTOUT/brent_price"] if brent is None else np.asarray(brent, dtype=np.float64)
        power0 = self._power_fuel(d_elec_us)
        cp87 = self._cp87(carbon_price)
        # Power plants switch fuel as fuel costs (carbon included) move, which moves gas
        # use, which moves the gas price: iterate to a fixed point (a few rounds).
        power = power0
        if power_fuel is not None:
            power = {**power0, **{k: np.asarray(v, dtype=np.float64) for k, v in power_fuel.items()}}
        for _ in range(0 if power_fuel is not None else SWITCH_ROUNDS):
            totals = self._totals(q, power)
            prices = self._prices(totals, brent)
            new = self._switch(power0, prices, cp87)
            change = max(float(np.max(np.abs(new[k] - power[k]) / (np.abs(power[k]) + 1.0))) for k in new)
            # Damped steps: gas burn and the gas price pull against each other, and a full
            # step can overshoot back and forth.
            power = {k: power[k] + 0.7 * (new[k] - power[k]) for k in new}
            if change < SWITCH_TOL:
                break
        totals = self._totals(q, power)
        prices = self._prices(totals, brent)

        all_q = {**{k: v for k, v in base.items() if k.startswith("QBLK/")}, **q, **power}
        co2 = {}
        for s in EMISSION_SECTORS:
            co2[s] = self._calibration[s] * self._carbon(s, all_q) * CO2_PER_C
        if co2_el is not None:
            co2["el"] = np.asarray(co2_el, dtype=np.float64)

        adders = {}
        if carbon_price is not None:
            adders = self._carbon_adders(carbon_price, co2["el"], totals["QBLK/qelas"])
            for name, a in adders.items():
                prices[name] = prices[name] + a
        return Result(prices, power, co2, totals, adders)

    def _carbon_adders(self, carbon_price, co2_el, elec_sales) -> dict[str, np.ndarray]:
        cp87 = self._cp87(carbon_price)
        el_intensity = np.divide(co2_el[US], elec_sales[US], out=np.zeros(61),
                                 where=elec_sales[US] > 0)  # t CO2 per MMBtu sold
        adders = {}
        for name in self.base:
            if not name.startswith("MPBLK/p"):
                continue
            fuel, sector = parse_price(name)
            if fuel == "el":
                per_mmbtu = el_intensity
            elif fuel in DRIVERS and fuel not in ("pf", "as"):  # feedstocks and asphalt are not burned
                per_mmbtu = carbon_factor(self.base, "ng" if fuel in ("gf", "gi") else fuel, sector)
                if per_mmbtu is None:
                    continue
            else:
                continue
            a = np.broadcast_to(cp87 * per_mmbtu, (11, 61)).copy()
            a[self.base[name] == 0] = 0.0  # no adder where the fuel has no price (not sold)
            adders[name] = a
        return adders


def year_index(year: int) -> int:
    return year - FIRST_YEAR
