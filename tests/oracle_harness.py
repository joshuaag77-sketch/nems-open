"""Generic oracle test: a new port needs a few lines instead of a hand-written test file.

    from oracle_harness import oracle_test
    from nems_open.commercial.consumption import consumption

    oracle_test(globals(), tag="cn", port=consumption, outputs=["enduseconsump", "cmeffind"])

For each year and each output name this loads `<tag>_in` (EIA's state just before the routine),
calls `port(inputs, year)`, and compares the named output with `<tag>_out` (just after) within
the float32 tolerance. One parametrized test per (year, output); skipped until the oracle has run.

Options (all keyword):
  module   which oracle ("comm" default, or "resd")
  years    dump years, default the nine test years (2019 to 2050)
  tol      max relative error, default 1e-4
  inputs   function (before, after, year) -> dict handed to the port. Default: a copy of `before`.
           Use it to add inputs only the routine sees (private tables dumped at `_out`, other tags).
  select   function (obj, name, year) -> array, applied to both sides. Default: the whole array.
           Use it to compare one year or skip regions EIA never rewrites.
  call     function (port, inputs, year) -> result, if the port is not called as port(inputs, year).
  get      function (result, name) -> value, default result[name] for dicts, else getattr.
"""

import numpy as np
import pytest

from nems_open import oracle_state

YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]  # 2019 ... 2050
TOL = 1e-4


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


def _array(x):
    return x.a if hasattr(x, "a") else x


def _get(res, name):
    return res[name] if isinstance(res, dict) else getattr(res, name)


def oracle_test(namespace, *, tag, port, outputs, module="comm", years=YEARS, tol=TOL,
                inputs=None, select=None, call=None, get=_get):
    """Define `test_<tag>` in `namespace` (pass globals())."""
    cache = {}

    def result(y):
        if y not in cache:
            before = oracle_state.load(f"{tag}_in", y, module)
            after = oracle_state.load(f"{tag}_out", y, module)
            inp = inputs(before, after, y) if inputs else dict(before)
            cache[y] = (call(port, inp, y) if call else port(inp, y)), after
        return cache[y]

    @pytest.mark.skipif(not oracle_state.available(f"{tag}_out", years[0], module), reason="oracle state not dumped")
    @pytest.mark.parametrize("y", years, ids=lambda y: str(1989 + y))
    @pytest.mark.parametrize("name", outputs)
    def test_output(y, name):
        res, after = result(y)
        mine, eia = get(res, name), after[name.lower()]
        if select:
            mine, eia = select(mine, name, y), select(eia, name, y)
        assert rel_err(_array(mine), _array(eia)) < tol, name

    test_output.__name__ = f"test_{tag}_output"
    namespace[test_output.__name__] = test_output
    return test_output
