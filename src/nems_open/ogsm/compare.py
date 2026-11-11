"""Compare HSM's OGSMOUT arrays from run_hsm with the reference restart, year by year."""
import numpy as np

from nems_open.paths import REFERENCE_RUN


def compare(out_npz, first_year=2024):
    ref, out = np.load(REFERENCE_RUN), np.load(out_npz)
    rows = []
    for n in out.files:
        a, b = out[n].astype(float), ref["OGSMOUT/" + n].astype(float)
        if a.shape != b.shape or a.ndim == 0 or a.shape[-1] != 61:
            continue
        s = slice(first_year - 1990, 61)
        a, b = a[..., s], b[..., s]
        scale = np.abs(b).max()
        if scale == 0:
            continue
        rows.append((n, float(np.abs(a - b).max() / scale), float(np.abs(b).max())))
    return sorted(rows, key=lambda r: -r[1])
