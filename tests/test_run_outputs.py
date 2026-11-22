"""The arrays a run saves (full_model.save_run) cover every line of the AEO report (scripts/aeo_fidelity.py).

A fake run built from cb2026's own arrays, with every field run_model fills, is saved and read back by the report:
no line may come out NOT IN RUN. Lines the model takes as inputs (Brent, WTI) or does not recompute come out HELD,
which is the honest label. Reads the cb2026 arrays only; no solve."""

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nems_open.supply_standin import data  # noqa: E402

pytestmark = pytest.mark.skipif(not data.available("cb2026"), reason="needs the cb2026 restart")


def _fake_run():
    import aeo_fidelity as af
    from nems_open.run_model import GAS_VOLUMES, RUN_EXTRA
    base = data.load_case("cb2026")
    eia = af.Eia()
    years = np.arange(61) + 1990
    solved = years >= 2027
    gen = {}
    for key, (ours, _) in af.GEN.items():
        for g in ours:
            gen[g] = np.where(solved, 1.02 * eia.gen(key) / len(ours), np.nan)
    groups = {g for ours, _ in af.CAP.values() for g in ours}
    cap = {y: SimpleNamespace(capacity={g: np.ones(25) for g in groups}) for y in (2030, 2035, 2040, 2050)}
    gas = {"henry_hub": eia.henry_hub(), **{k: np.ones(61) * 100.0 for k in GAS_VOLUMES}}
    extra = {k: np.ones(61) for k in RUN_EXTRA}
    co2 = {s: np.asarray(base[f"EMISSION/{a}"], dtype=float)[:, 0] * af.CO2_PER_C for s, a in af.CO2_ARRAYS.items()}
    return SimpleNamespace(
        prices={k: v for k, v in base.items() if k.startswith("MPBLK/")},
        quantities={k: v for k, v in base.items() if k.startswith("QBLK/")},
        co2=co2, generation_twh=gen, gas=gas, capacity=cap, extra=extra,
        stable={y: True for y in range(2027, 2051)}), eia


def test_saved_arrays_cover_every_report_line(tmp_path):
    import aeo_fidelity as af
    import full_model as fm
    r, eia = _fake_run()
    fm.save_run(r, tmp_path / "run.npz")
    res = af.compare(af.Run(tmp_path / "run.npz", eia), eia)
    missing = [(x["table"][:8], x["series"]) for x in res["lines"] if x["status"] in ("NOT IN RUN", "NO EIA VALUE")]
    assert not missing, missing


def test_power_inputs_follow_generation(tmp_path):
    """QUREL and QTREL move with generation (2% above EIA's here), so they are no longer HELD."""
    import aeo_fidelity as af
    import full_model as fm
    r, eia = _fake_run()
    fm.save_run(r, tmp_path / "run.npz")
    res = af.compare(af.Run(tmp_path / "run.npz", eia), eia)
    nuc = next(x for x in res["lines"] if x["series"] == "Electric power: Nuclear")
    assert nuc["status"] == "PASS" and abs(nuc["years"][2040]["diff_pct"] - 2.0) < 1e-6
    ren = next(x for x in res["lines"] if x["series"] == "Electric power: Renewable energy")
    assert ren["status"] != "HELD"
