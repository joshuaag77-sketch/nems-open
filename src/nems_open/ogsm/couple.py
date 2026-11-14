"""EIA's HSM (oil and gas supply) inside a run: production for the prices the run settled on.

The stand-in has no production at all, only price curves, so HSM does not replace a stand-in
calculation; it adds the quantities. HSM reads wellhead gas prices (NGTDMREP/ogprcng, ogwprng) and
crude prices (LFMMOUT/rfcrudewhp) from the restart. We scale the cb2026 values by how far the run's
prices moved from the baseline (US power-sector gas price for gas, Brent for crude) and run HSM once over
the whole horizon (about 9 minutes, one core). Results are cached by their inputs.

What this is not: a market clearing. Natural gas prices still come from the stand-in; HSM's
production does not feed back into them, because the gas market model (NGMM, AIMMS) is not here.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from nems_open.ogsm.run_hsm import work_dir

PRICE_BLOCKS = {"gas": ("NGTDMREP/ogprcng", "NGTDMREP/ogwprng"), "oil": ("LFMMOUT/rfcrudewhp",)}
# The arrays callers usually want, with units as in the restart file.
HEADLINE = ("ogngprd", "ogcoprd", "ognowell", "ogqngrep")


def scale_for(gas_ratio, oil_ratio) -> dict:
    """Ratio arrays (61,) keyed by restart array. None means no change."""
    out = {}
    for ratio, blocks in ((gas_ratio, PRICE_BLOCKS["gas"]), (oil_ratio, PRICE_BLOCKS["oil"])):
        if ratio is None:
            continue
        r = np.nan_to_num(np.asarray(ratio, dtype=np.float64), nan=1.0, posinf=1.0, neginf=1.0)
        if not np.allclose(r, 1.0):
            out.update({b: r for b in blocks})
    return out


def _key(scedes: str, scale: dict) -> str:
    h = hashlib.sha1(scedes.encode())
    for k in sorted(scale):
        h.update(k.encode())
        h.update(np.round(scale[k], 6).tobytes())
    return h.hexdigest()[:16]


def production(gas_ratio=None, oil_ratio=None, scedes: str = "scedes.cb2026.csv", verbose: bool = False) -> dict:
    """HSM's OGSMOUT arrays (name -> array, year axis last, 1990 to 2050) for prices moved by the ratios."""
    scale = scale_for(gas_ratio, oil_ratio)
    cache = work_dir().parent / "ogsm-cache"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{_key(scedes, scale)}.npz"
    if not out.exists():
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.npz"
            np.savez(src, scedes=scedes, **{"scale/" + k: v for k, v in scale.items()})
            part = Path(tmp) / "out.npz"
            env = {**os.environ, "OMP_NUM_THREADS": "1",
                   "PYTHONPATH": os.pathsep.join([str(Path(__file__).resolve().parents[2]), os.environ.get("PYTHONPATH", "")])}
            r = subprocess.run([sys.executable, "-m", "nems_open.ogsm.worker", str(src), str(part)],
                               env=env, cwd=Path(tmp), capture_output=not verbose, text=True)
            if r.returncode or not part.exists():
                raise RuntimeError("HSM run failed:\n" + (r.stderr or "")[-2000:])
            part.replace(out) if part.drive == out.drive else out.write_bytes(part.read_bytes())
    with np.load(out) as z:
        return {k: z[k] for k in z.files}
