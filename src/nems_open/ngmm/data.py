"""The gas-market arrays of EIA's AEO2026 runs, cached small (data/aeo2026/ngmm_<case>.npz, git-ignored).

    python -m nems_open.ngmm.data      # rebuild the cache from the upstream restart files
"""
import os
import sys

import numpy as np

from nems_open.supply_standin.data import CACHE, CASES, restart_path

PREFIXES = ("NGTDMREP/", "MPBLK/png", "MPBLK/pgf", "MPBLK/pgi")
SINGLE = ("QBLK/qngas", "QBLK/qlpin", "QBLK/qgptr", "CONVFACT/cfngc", "MACOUT/mc_jpgdp",
          "OGSMOUT/ogngprd", "OGSMOUT/ogenagprd", "OGSMOUT/ogrnagprd")


def path(case: str):
    return CACHE / f"ngmm_{case}.npz"


def extract(case: str):
    z = np.load(restart_path(case), allow_pickle=False)
    keep = {k: z[k] for k in z.files if k.startswith(PREFIXES) or k in SINGLE}
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / f"ngmm_{case}.{os.getpid()}.tmp.npz"
    np.savez_compressed(tmp, **keep)
    try:
        os.replace(tmp, path(case))
    except PermissionError:   # another process has it open; its copy is identical
        tmp.unlink(missing_ok=True)
    return path(case)


_loaded: dict[str, dict] = {}


def load(case: str = "cb2026") -> dict[str, np.ndarray]:
    if case not in _loaded:
        if not path(case).exists():
            extract(case)
        with np.load(path(case), allow_pickle=False) as z:
            _loaded[case] = {k: z[k].astype(np.float64) for k in z.files}
    return _loaded[case]


if __name__ == "__main__":
    for c in CASES:
        print(c, extract(c))
    sys.exit(0)
