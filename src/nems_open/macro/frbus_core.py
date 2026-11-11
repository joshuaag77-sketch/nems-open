"""FRB/US core of the economy module, pinned to EIA's reference GDP.

EIA's own macro model is S&P's EViews workfile, which is not public. Here the Fed's FRB/US
(pyfrbus) stands in. Add-factors on consumption (eco_aerr) and the housing/labour block (lhp_aerr)
force real GDP to follow EIA's MC_GDPR growth and unemployment to follow FRB/US's baseline (natural rate from 2036),
so a run with the reference energy path reproduces EIA's reference economy. Shocks to the energy
path then move the economy off that reference.

pyfrbus is not on PyPI. Download it from federalreserve.gov/econres/us-models-python.htm and point
NEMS_FRBUS_DIR at the unpacked pyfrbus folder (default: third_party/frbus/py/pyfrbus).
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from nems_open.paths import REFERENCE_RUN

ROOT = Path(__file__).resolve().parents[3]
FRBUS_DIR = Path(os.environ.get("NEMS_FRBUS_DIR", ROOT / "third_party" / "frbus" / "py" / "pyfrbus"))
FIRST_YEAR, LAST_YEAR = 2026, 2050


def available() -> bool:
    return (FRBUS_DIR / "models" / "model.xml").exists() and (FRBUS_DIR / "data" / "LONGBASE.TXT").exists()


def eia_gdp_path(snapshot_path: Path = REFERENCE_RUN) -> pd.Series:
    """EIA real GDP (MC_GDPR), annual, indexed by calendar year 1990 to 2050."""
    g = np.load(snapshot_path)["MACOUT/mc_gdpr"]
    return pd.Series(g, index=np.arange(1990, 1990 + len(g)))


def quarterly_target(annual: pd.Series, start: pd.Period, end: pd.Period) -> pd.Series:
    """Annual levels to quarterly by log-linear interpolation through mid-year points."""
    q = pd.period_range(start - 1, end, freq="Q")
    x = np.array([p.year + (p.quarter - 0.5) / 4 for p in q])
    return pd.Series(np.exp(np.interp(x, annual.index + 0.5, np.log(annual.values))), index=q)


class Economy:
    """FRB/US with add-factors that reproduce EIA's reference GDP growth."""

    def __init__(self, snapshot_path: Path = REFERENCE_RUN):
        if not available():
            raise RuntimeError("pyfrbus not found; see the module docstring")
        if str(FRBUS_DIR) not in sys.path:
            sys.path.insert(0, str(FRBUS_DIR))
        from pyfrbus.frbus import Frbus
        from pyfrbus.load_data import load_data

        self.start = pd.Period(f"{FIRST_YEAR}Q1")
        self.end = pd.Period(f"{LAST_YEAR}Q4")
        data = load_data(str(FRBUS_DIR / "data" / "LONGBASE.TXT"))
        data.loc[self.start : self.end, "dfpdbt"] = 0  # surplus-ratio fiscal rule
        data.loc[self.start : self.end, "dfpsrp"] = 1
        self.model = Frbus(str(FRBUS_DIR / "models" / "model.xml"))
        traced = self.model.init_trac(self.start, self.end, data)
        eia = eia_gdp_path(snapshot_path)
        tgt = quarterly_target(eia, self.start, self.end)
        traced["xgdp_t"] = traced.loc[self.start - 1, "xgdp"] * (tgt / tgt.loc[self.start - 1])
        # LONGBASE's mechanical extrapolation has an artificial unemployment swing after 2040: hold the
        # natural rate from 2036 on.
        late = [p.year >= 2036 for p in traced.loc[self.start : self.end].index]
        traced["lur_t"] = traced["lur"]
        traced.loc[self.start : self.end, "lur_t"] = np.where(late, traced.loc[self.start : self.end, "lurnat"], traced.loc[self.start : self.end, "lur"])
        self.reference = self.model.mcontrol(
            self.start, self.end, traced, ["xgdp", "lur"], ["xgdp_t", "lur_t"], ["eco_aerr", "lhp_aerr"]
        )
        self.eia_gdp = eia

    def annual(self, frame: pd.DataFrame, var: str) -> pd.Series:
        s = frame.loc[self.start : self.end, var]
        return s.groupby(lambda p: p.year).mean()

    def run(self, oil_multiplier: float | pd.Series = 1.0) -> pd.DataFrame:
        """Solve with the real imported-oil price (poilr) held at the reference path times a multiplier.

        A float scales every quarter; a Series indexed by calendar year scales each year.
        """
        data = self.reference.copy()
        if isinstance(oil_multiplier, pd.Series):
            years = pd.Series([p.year for p in data.loc[self.start : self.end].index], index=data.loc[self.start : self.end].index)
            mult = years.map(oil_multiplier).astype(float)
        else:
            mult = float(oil_multiplier)
        data.loc[self.start : self.end, "poilr"] = self.reference.loc[self.start : self.end, "poilr"] * mult
        self.model.exogenize(["poilr"])
        return self.model.solve(self.start, self.end, data)
