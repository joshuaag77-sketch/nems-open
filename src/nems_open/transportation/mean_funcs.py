"""MODULE MEAN_FUNCS (tran.f): weighted and harmonic means of 1-3 dimensional arrays.

One function per kind covers EIA's 1D, 2D and 3D versions, which differ only in rank.
"""

import numpy as np

from nems_open.transportation.common import f32, fsum


def weighted_mean(values, weights, caller_id=""):
    values, weights = np.asarray(values, dtype=f32), np.asarray(weights, dtype=f32)
    if np.isnan(values).any():
        raise ValueError(f"ERROR TDM: (WEIGHTED_MEAN {caller_id}): Input VALUES array contains NaN.")
    if values.shape != weights.shape:
        raise ValueError(f"ERROR TDM: (WEIGHTED_MEAN {caller_id}): VALUES and WEIGHTS must have the same size.")
    total = fsum(weights)
    if total == 0.0:
        return f32(0.0)
    return fsum(values * weights) / total


def harmonic_mean(mpgs, weights, creds=None, caller_id=""):
    """Sales- or stock-weighted harmonic mean of fuel economy; CREDS are per-mile credits
    taken off 1/MPG (2D and 3D versions only). Zero MPGs or weights drop out."""
    mpgs, weights = np.asarray(mpgs, dtype=f32), np.asarray(weights, dtype=f32)
    if mpgs.shape != weights.shape:
        raise ValueError(f"ERROR TDM: (HARMONIC_MEAN {caller_id}): MPGS and WEIGHTS must have the same shape.")
    total = fsum(weights)
    if total == 0.0:
        return f32(0.0)
    valid = (mpgs != 0.0) & (weights != 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = f32(1.0) / mpgs
        if creds is not None:
            inv = inv - np.asarray(creds, dtype=f32)
        terms = np.where(valid, weights * inv, f32(0.0)).astype(f32)
    num = fsum(terms)
    if num == 0.0:
        return f32(0.0)
    return total / num
