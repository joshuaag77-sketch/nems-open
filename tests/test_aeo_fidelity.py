"""The AEO fidelity report on a tiny fixture: no restart, no saved run, a few arrays by hand."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import aeo_fidelity as af  # noqa: E402

J = np.arange(61) + 1990


def _us(before, after):
    a = np.zeros((11, 61))
    a[10] = np.where(J < 2027, before, after)
    return a


def _fixture():
    eia = af.Eia({
        "QBLK/qelrs": _us(100.0, 100.0),          # trillion Btu
        "QBLK/qngrs": _us(50.0, 50.0),
        "MPBLK/pelrs": _us(10.0, 10.0),           # 1987 $/MMBtu
        "MACOUT/mc_jpgdp": np.ones(64),           # dollar factor 1
        "MACOUT/mc_gdpr": np.full(61, 20000.0),
        "UDATOUT/ucapnuu": np.full((28, 61), 4.0),
    })
    cap = np.zeros((61, 25))
    cap[2030 - 1990:] = 4.4                       # 110 GW against EIA's 100: inside 15%; zero before 2030 = not solved
    run = af.Run({
        "q:QBLK/qelrs": _us(100.0, 102.0),        # +2%: inside 3%
        "q:QBLK/qngrs": _us(50.0, 50.0),          # EIA's own number carried through
        "p:MPBLK/pelrs": _us(10.0, 12.0),         # +20%: outside 5%
        "k:capacity:nuclear": cap,
        "stable": np.array([[2027, 1], [2030, 0]]),
    }, eia)
    return run, eia


def _line(res, table, series):
    return next(r for r in res["lines"] if r["table"].startswith(table) and r["series"] == series)


def test_statuses_and_diffs():
    run, eia = _fixture()
    res = af.compare(run, eia)
    elec = _line(res, "Table 2", "Residential: Purchased electricity")
    assert elec["status"] == "PASS"
    assert abs(elec["years"][2030]["diff_pct"] - 2.0) < 1e-9
    assert elec["years"][2025]["graded"] is False and elec["years"][2030]["converged"] is False
    price = _line(res, "Table 3", "Residential: Electricity")
    assert price["status"] == "FLAG" and abs(price["years"][2050]["diff_pct"] - 20.0) < 1e-9
    assert abs(price["years"][2050]["eia"] - 10.0 * af.MMBTU_PER_KWH * 100) < 1e-9     # cents/kWh
    assert _line(res, "Table 2", "Residential: Natural gas")["status"] == "HELD"
    assert _line(res, "Macro", "Real gross domestic product")["status"] == "NOT IN RUN"
    assert _line(res, "Table 1", "Prices: Brent spot")["status"] == "NO EIA VALUE"
    nuc = _line(res, "Table 9", "Electric power sector capacity: Nuclear")
    assert nuc["status"] == "PASS" and nuc["years"][2025]["ours"] is None
    assert abs(nuc["years"][2030]["ours"] - 110.0) < 1e-9 and abs(nuc["years"][2030]["eia"] - 100.0) < 1e-9


def test_worst_lists_each_series_once_and_report_renders():
    run, eia = _fixture()
    res = af.compare(run, eia)
    w = af.worst(res)
    assert w[0]["source"] == "MPBLK/PELRS" and sum(r["source"] == "MPBLK/PELRS" for r in w) == 1
    md = af.markdown(res, "fixture")
    assert "## Worst 15 lines" in md and "Table 13. Natural gas" in md and chr(0x2014) not in md
    js = af.to_json(res, "fixture", "fixture.npz")
    assert js["lines"][0]["years"]["2030"].keys() >= {"ours", "eia", "diff_pct", "ok"}
