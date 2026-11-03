"""Run our residential and commercial demand modules from one AEO vintage's input files.

    python -I scripts/aeo_diff_run.py 2025|2026 YEAR out.json [more years...]

The vintage picks the input files (`NEMS_UPSTREAM`: the 2025 tag lives in data/aeo2025/tag, read as data)
and the restart file that supplies prices, macro drivers and other modules' outputs. Both modules start
from their input files, never from the 2026 oracle dumps, so the two vintages are run the same way.
The code is always the one in this checkout, which is ported from the AEO2026 source.
"""

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
vintage, out = sys.argv[1], Path(sys.argv[2])
years = [int(a) for a in sys.argv[3:]] or [2030]
if vintage == "2025":
    os.environ["NEMS_UPSTREAM"] = str(ROOT / "data" / "aeo2025" / "tag")
    os.environ["NEMS_SCENARIO"] = "ref2025"
    snapshot_path = ROOT / "data" / "aeo2025" / "restart2025.npz"
sys.path.insert(0, str(ROOT / "src"))

from nems_open import run_demand                      # noqa: E402  (after NEMS_UPSTREAM is set)
from nems_open.paths import REFERENCE_RUN             # noqa: E402
from nems_open.snapshot import Snapshot               # noqa: E402

if vintage == "2026":
    snapshot_path = REFERENCE_RUN
if vintage == "drivers25":          # 2026 module input files and code, driven by the 2025 restart's prices and macro
    snapshot_path = ROOT / "data" / "aeo2025" / "restart2025.npz"
run_demand.ResidentialSector.dumped = staticmethod(lambda year: False)

result = {}
for year in years:
    t0 = time.time()
    inputs = run_demand.Inputs(Snapshot(snapshot_path))
    runner = run_demand.DemandRunner(year, inputs, sectors=tuple(os.environ.get("AEO_SECTORS", "residential,commercial").split(",")), commercial_from_files=True)
    runner.run_year()
    j = year - run_demand.BASEYR
    ref = run_demand.eia_quantities(inputs.snapshot)
    result[year] = {
        "ours": {k: float(v[run_demand.MNUMCR - 1, j]) for k, v in runner.q.items() if k.startswith(("qt", "qel", "qng", "qcl", "qdi", "qlg", "qkr", "qpr", "qsl", "qmg", "qrs", "qcm", "qht", "qge", "qwd", "qso", "qpv", "qot"))},
        "restart": {k: float(v[run_demand.MNUMCR - 1, j]) for k, v in ref.items() if k.startswith(("qt", "qel", "qng", "qcl", "qdi", "qlg", "qkr", "qpr", "qsl", "qmg", "qrs", "qcm", "qht", "qge", "qwd", "qso", "qpv", "qot"))},
        "seconds": time.time() - t0,
    }
    print(year, "done", round(time.time() - t0), "s", flush=True)
out.write_text(json.dumps({"vintage": vintage, "years": result}, indent=1))
