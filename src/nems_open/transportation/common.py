"""Dimensions and helpers shared by the transportation ports (MODULE T_ in tran.f)."""

import numpy as np

f32 = np.float32

BASEYR = 1990
MNUMCR = 11      # 9 census divisions, California (10, filled elsewhere), US (11)
MNUMYR = 61
AGEGRP = 5       # licensed-driver age groups
MF = 2           # 1 male, 2 female
MAXVTYP = 2      # 1 car, 2 light truck
MAXOWNER = 5     # household, business, government, utility, taxi
MAXLDV = 16      # fuel/powertrain types
MAXAGE = 25
MAXHAV = 4
STOCKYR = 2024   # last year of census-division stock history


def fsum(a, axis=None):
    """Fortran SUM on REAL*4: one float32 accumulator, added in index order.

    numpy's float32 sum is pairwise, which rounds differently. gfortran adds element by
    element; np.add.accumulate does too. The Fortran accumulator starts at +0, so its
    sum is never -0.0: adding +0 to the last partial sum gives that.
    """
    a = np.asarray(a, dtype=f32)
    if axis is None:
        a = a.reshape(-1, order="F")
        axis = 0
    if a.shape[axis] == 0:
        acc = np.zeros(a.shape[:axis] + a.shape[axis + 1:], dtype=f32)
        return acc if acc.ndim else f32(acc)
    last = np.take(np.add.accumulate(a, axis=axis, dtype=f32), -1, axis=axis) + f32(0.0)
    return last if last.ndim else f32(last)


def _single(r):
    r = np.asarray(r)
    return r.astype(f32) if r.ndim else f32(r)


def expf(x):
    """REAL*4 EXP as the oracle's libm gives it: correctly rounded, which double
    precision rounded once reproduces. NumPy's float32 exp can be an ulp off."""
    return _single(np.exp(np.asarray(x, dtype=np.float64)))


def logf(x):
    """REAL*4 LOG, rounded once from double precision (see expf)."""
    return _single(np.log(np.asarray(x, dtype=np.float64)))


def powf(x, y):
    """REAL*4 ** REAL*4, rounded once from double precision (see expf)."""
    return _single(np.power(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)))


def fmax(a, b):
    """gfortran's MAX of two scalars: a NaN argument gives the other one."""
    if a != a:
        return b
    if b != b:
        return a
    return a if a >= b else b


def fmin(a, b):
    """gfortran's MIN of two scalars: a NaN argument gives the other one."""
    if a != a:
        return b
    if b != b:
        return a
    return a if a <= b else b
