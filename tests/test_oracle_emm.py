"""Smoke test for the electricity (EMM) Fortran oracle. Skipped until it has run.

Build and run it first (SCOPE.md, "Electricity oracle"). The oracle runs EIA's own
LDSM (load) and EFP (pricing) Fortran on a saved NEMS run, but EMM's two LP
solves (ECP capacity, EFD dispatch) run in AIMMS, which we do not have. ECP is
skipped and EFD is replaced by a stand-in that fills each region's dispatch
results from EIA's regional totals (oracle/efd_standin.f90). So:

- LDSM sees EIA's demand and runs as EIA wrote it.
- EFP's dumps check the routine's arithmetic for a Python port, routine by
  routine. Its prices are NOT EIA's prices and are not compared to them here.
  Rerun once our dispatch LP supplies the EFD block.
"""

import numpy as np
import pytest

from nems_open import oracle_state

pytestmark = pytest.mark.skipif(not oracle_state.available("final", 61, "emm"), reason="oracle not run")

YEARS = [31, 32, 33, 36, 37, 38, 41, 51, 61]  # 2020 2021 2022 2025 2026 2027 2030 2040 2050
TAGS = ["ld_in", "ld_out", "fp_in", "fp_out", "fs_out"]


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_dumps_exist(tag, y):
    assert oracle_state.available(tag, y, "emm"), (tag, y)
    d = oracle_state.load(tag, y, "emm")
    assert len(d) > 50, (tag, y, len(d))


def not_finite(d):
    """Names of float arrays in a dump holding NaN or infinity."""
    return {k for k, v in d.items() if hasattr(v, "a") and v.a.dtype.kind == "f" and not np.isfinite(v.a).all()}


# EFP's regression variables (uefp.f around line 3533) divide 0 by 0 in every
# region on the stand-in inputs. Nothing downstream reads a NaN from them: prices
# stay finite. Recheck once the dispatch LP supplies the EFD block (SCOPE.md).
EFP_NAN = {"tmsint", "trnpct", "dstpct", "bldrat", "nucpct"}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_no_new_nan(y):
    assert not not_finite(oracle_state.load("ld_out", y, "emm"))
    assert not_finite(oracle_state.load("fp_out", y, "emm")) <= EFP_NAN


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_ldsm_builds_load(y):
    # LDSM's hourly system load, SYSLDHR(year, EMM region, hour): positive in all
    # 25 regions.
    load = oracle_state.load("ld_out", y, "emm")["sysldhr"].a[y - 1]
    assert (load.sum(axis=1) > 0).all()


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_efp_sets_prices(y):
    # EFP writes retail prices by census division and by EMM region. Arithmetic
    # check only: positive and finite.
    after = oracle_state.load("fp_out", y, "emm")
    p = after["pelas"].a[:9, y - 1]
    assert (p > 0).all() and np.isfinite(p).all()
    assert after["pelrsnr"].a[:25, y - 1].min() > 0  # 26-28 (Alaska, Hawaii, US) are filled elsewhere


def test_region_blocks_per_region():
    # The stand-in's per-region EFD output block, one set of arrays per region.
    d = oracle_state.load("fs_out", 41, "emm")
    regions = {k.rsplit("_r", 1)[1] for k in d if "_r" in k}
    assert len(regions) >= 25
    assert d["ertfl_r01"].a.sum() > 0
