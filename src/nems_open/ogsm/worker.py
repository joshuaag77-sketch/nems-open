"""One HSM run in its own process (HSM's modules keep global state, so one run per process).

    python -m nems_open.ogsm.worker IN.npz OUT.npz

IN.npz holds `scedes` (file name) and optional `scale/<BLOCK>/<var>` ratio arrays; OUT.npz gets every
OGSMOUT array HSM wrote.
"""
import sys

import numpy as np

from nems_open.ogsm import run_hsm


def main(src: str, dst: str) -> None:
    with np.load(src, allow_pickle=False) as z:
        scedes = str(z["scedes"])
        scale = {k[len("scale/"):]: z[k] for k in z.files if k.startswith("scale/")}
    p = run_hsm.run(scedes=scedes, scale=scale)
    ns = p.__getattr__("ogsmout")
    np.savez(dst, **{k: np.asarray(v) for k, v in vars(ns).items() if not k.startswith("_")})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
