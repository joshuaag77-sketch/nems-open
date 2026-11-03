"""Set orderings and dense arrays for the CMM's parameters.

AIMMS keys parameters by element name; NEMS arrays are positional. `elements(set)` gives the order the
input files list a set in (the order the model's mapping tables use), and `dense` lays a parameter out as
a numpy array over its domain, NaN where the files give no value.
"""

import numpy as np

from nems_open.coal import aimms_data as ad
from nems_open.coal.inputs import load


def elements(set_name: str) -> list:
    d = ad.declarations()
    s = d.index_set.get(set_name.lower(), set_name.lower())
    return list(load().sets.get(s, []))


def dense(name: str) -> tuple[np.ndarray, list[list]]:
    """(array, axes): the parameter over the elements of each of its domain sets, NaN where absent."""
    p = load().params[name.lower()]
    axes = [elements(ix) for ix in p.domain]
    out = np.full([len(a) for a in axes] or [1], np.nan)
    pos = [{e: i for i, e in enumerate(a)} for a in axes]
    for key, v in p.data.items():
        if isinstance(v, (int, float)):
            out[tuple(pos[i][k] for i, k in enumerate(key))] = v
    return out, axes
