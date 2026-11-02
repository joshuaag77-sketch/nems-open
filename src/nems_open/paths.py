"""Where the upstream EIA NEMS checkout and reference runs live."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Override with NEMS_UPSTREAM to point at a different EIA checkout.
UPSTREAM = Path(os.environ.get("NEMS_UPSTREAM", REPO_ROOT / "nems-upstream"))

INPUT = UPSTREAM / "input"

# AEO2026 reference case, the answer key for every port.
REFERENCE_RUN = UPSTREAM / "output" / "aeo2026" / "cb2026" / "d011626a" / "restart.npz"
