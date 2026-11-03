"""TRAN's first-call input readers vs the oracle.

Each reader fills its arrays from EIA's input files; every array it fills must equal
the oracle's state at the top of 2020 (the first dump year), where nothing the module
did since its first call has touched those values.
"""

import numpy as np
import pytest

from nems_open.fortran_array import FArray
from nems_open.transportation import tran
from nems_open.transportation.readers import air
from tran_harness import needs, rel_err

pytestmark = needs("tran_tail")
Y = 31  # 2020

READERS = {
    "readair": (air.readair, [
        "wld_pop", "wld_gdp", "qagtr_us", "load_factor", "shr_ftm", "shr_rpm", "rpmt_hist", "ftmac", "asmac",
        "stkpa", "stkpp", "stkca", "stkcp", "stkpavint", "stkcavint", "stkppvint", "stkcpvint", "survac",
        "stk_sup_new", "min_prk_shr", "gptm", "pct_pass_mtow", "pct_belly_pload", "pct_belly_frt",
        "air_mgmt_adj", "stk_align_mult", "intercept_rpm", "beta1_rpm", "covidmult_ref", "covidmult_lomac",
        "covidmult_himac", "intercept_ftm", "beta1_ftm", "pass_weight", "fuel_burn_red", "alphayd", "rhoyd",
        "betafueld", "betatimed", "alphayi", "rhoyi", "betafueli", "betatimei", "minage_prk_f",
        "minage_c_pprk", "minage_c_pact", "minage_prk_p", "maxage_unprk_p", "max_unprk_shr",
        "stk_sup_tot", "stkptot", "stkctot", "covid_mult"], "a_"),
}
# Arrays the reader fills only in part; the rest is the module's own later output, compared
# on the reader's part: {name: index}.
PART = {
    "readair": {"yield": (slice(None), slice(5, 33)), "ftm": (slice(None), slice(5, 33), slice(None)),
                "asmpg_vint": (slice(None), slice(None), slice(None), slice(None), 32)},
}


@pytest.fixture(scope="module")
def start():
    return tran.start_from_dump(Y)[0]


@pytest.mark.parametrize("reader", list(READERS))
def test_reader(start, reader):
    fn, names, prefix = READERS[reader]
    key = lambda k: prefix + k if prefix + k in start else k  # noqa: E731
    part = {key(k): idx for k, idx in PART[reader].items()}
    keys = [key(k) for k in names] + list(part)
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in start.items()}
    for k in keys:
        if isinstance(s[k], FArray):
            s[k].a[...] = 0
        else:
            s[k] = type(s[k])(0)
    fn(s)
    bad = {}
    for k in keys:
        mine, eia = s[k], start[k]
        idx = part.get(k)
        m = mine.a[idx] if idx is not None else (mine.a if isinstance(mine, FArray) else np.asarray(mine))
        e = eia.a[idx] if idx is not None else (eia.a if isinstance(eia, FArray) else np.asarray(eia))
        err = rel_err(m, e)
        if err > 0:
            bad[k] = err
    assert bad == {}
