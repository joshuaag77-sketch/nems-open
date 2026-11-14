"""Pure Python stand-in for EIA's compiled pyfiler1 (an f2py wrapper of the NEMS restart file).

HSM only needs attribute access: pyfiler1.<common block>.<variable> gives a numpy array in
Fortran dimension order. This loads the same arrays from a restart.npz. After a standalone HSM run
the arrays hold HSM's outputs, because HSM writes into them in place.
"""
import types

import numpy as np

_PARAMS = dict(ncrl=1, fcrl=1, baseyr=1990, gastypes=5, oiltypes=5, mnumor=14, mnumcr=11, mnumyr=61,
               ogdist=84, mnl48n=7, mnl48f=3, mnogcro=6, mncrud=11, mnumpr=10)

utils = types.SimpleNamespace(**_PARAMS)
utils.init_filer = lambda: None
utils.read_filer = lambda *a, **k: None
utils.write_filer = lambda *a, **k: None
other = types.SimpleNamespace(**_PARAMS)
_BLOCKS = {"utils": utils, "other": other}


def __getattr__(name):
    # Any other common block is created on first use, like an f2py module.
    if name.startswith("__"):
        raise AttributeError(name)
    return _BLOCKS.setdefault(name, types.SimpleNamespace())


def load(path):
    """Fill the common blocks from a restart.npz. Mirrors models/main/restart_load.py."""
    with np.load(path) as z:
        for key in z.files:
            if "/" not in key:
                continue
            block, var = key.split("/", 1)
            ns = _BLOCKS.setdefault(block.lower(), types.SimpleNamespace())
            # Fortran order and writable, as f2py hands them out.
            setattr(ns, var, np.asfortranarray(z[key]).copy(order="F") if z[key].ndim else z[key].item())
