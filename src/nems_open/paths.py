"""Where the upstream EIA NEMS checkout and reference runs live."""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_upstream() -> Path:
    """The EIA checkout (about 1 GB, git-ignored, so a fresh git worktree does not have it).

    In order: NEMS_UPSTREAM; `nems-upstream/` in this checkout; the same folder in the main checkout
    this worktree was made from; the same folder in a sibling checkout next to this one.
    """
    env = os.environ.get("NEMS_UPSTREAM")
    if env:
        return Path(env)
    here = REPO_ROOT / "nems-upstream"
    if here.exists():
        return here
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        if common:
            main = Path(common).parent / "nems-upstream"
            if main.exists():
                return main
    except (OSError, subprocess.SubprocessError):
        pass
    for sibling in sorted(REPO_ROOT.parent.glob("*/nems-upstream")):
        if (sibling / "input").exists():
            return sibling
    return here


# Override with NEMS_UPSTREAM to point at a different EIA checkout.
UPSTREAM = _find_upstream()

INPUT = UPSTREAM / "input"

# AEO2026 reference case, the answer key for every port.
REFERENCE_RUN = UPSTREAM / "output" / "aeo2026" / "cb2026" / "d011626a" / "restart.npz"
