"""Reproduce policy convergence in one process with stub demand and stand-in supply.

Run with PYTHONUTF8=1 and PYTHONPATH=src. Optional reference snapshots compare
every price, quantity and sector CO2 array against a pre-change run at atol=1e-9.
"""

import argparse
import os
from functools import partial
from pathlib import Path
from unittest.mock import patch

# Set these before importing NumPy; no demand workers or solver threads are used.
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[name] = "1"

import numpy as np

from nems_open.demand_adapter import Policy
from nems_open import demand_adapter
from nems_open.run_model import run
from nems_open.supply_standin.data import US


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=2027)
    ap.add_argument("--end", type=int, default=2050)
    ap.add_argument("--ev-share", type=float, default=1.0)
    ap.add_argument("--oil-price", type=float, default=2.0)
    ap.add_argument("--maxitr", type=int, default=None)
    ap.add_argument("--ported", nargs="*", default=[], choices=("residential", "commercial"))
    ap.add_argument("--save-reference", type=Path)
    ap.add_argument("--compare-reference", type=Path)
    ap.add_argument("--trace", action="store_true", help="print all iteration residuals")
    ap.add_argument("--track", nargs="*", default=[], metavar="KEY",
                    help="also print US values each iteration, e.g. MPBLK/ppfin QBLK/qpfin")
    args = ap.parse_args()
    opts = dict(start_year=args.start, end_year=args.end, ported=tuple(args.ported))
    if args.maxitr is not None:
        opts["maxitr"] = args.maxitr
    cases = {"reference": Policy(start_year=args.start),
             "high EV": Policy(ev_share=args.ev_share, start_year=args.start),
             "high oil": Policy(oil_price=args.oil_price, start_year=args.start)}
    for name, policy in cases.items():
        tracked = []

        def record(stage, **state):
            if stage == "supply":
                values = {**state["prices"], **state["q"]}
                row = " ".join(f"{k}={values[k][US, state['j']]:.9g}" for k in args.track)
                tracked.append(f"  {state['year']} itr {state['itr']}: {row}")

        # The integrated default normally starts a demand worker. Override only
        # scheduling so optional ported sectors also run in this one process.
        serial = partial(demand_adapter.PortedSectors, parallel=False)
        with patch.object(demand_adapter, "PortedSectors", serial):
            result = run(policy, **opts, record=record if args.track else None)
        print(f"\n{name}: {sum(result.stable.values())}/{len(result.stable)} years stable", flush=True)
        for year, stable in result.stable.items():
            if not stable:
                passes = [p for p in result.passes if p.year == year]
                for p in passes[1:]:
                    print(f"  {year} itr {p.number} FCRL={p.fcrl}: {', '.join(p.failing) or 'passed (no confirming pass)'}")
        if args.trace:
            print(result.report())
        if tracked:
            print("\n".join(tracked))
        if name == "reference":
            arrays = {f"{group}/{k}": v for group in ("prices", "quantities", "co2")
                      for k, v in getattr(result, group).items()}
            if args.save_reference:
                args.save_reference.parent.mkdir(parents=True, exist_ok=True)
                np.savez(args.save_reference, **arrays)
            if args.compare_reference:
                with np.load(args.compare_reference) as before:
                    assert set(before.files) == set(arrays)
                    for key, value in arrays.items():
                        np.testing.assert_allclose(value, before[key], rtol=0, atol=1e-9, err_msg=key)
                    delta = max(float(np.max(np.abs(value - before[key]))) for key, value in arrays.items())
                print(f"  Reference maximum absolute difference: {delta:.3g}")


if __name__ == "__main__":
    main()
