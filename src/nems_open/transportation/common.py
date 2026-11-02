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

    numpy's float32 sum is pairwise, which rounds differently. gfortran adds
    element by element, so this does too.
    """
    a = np.asarray(a, dtype=f32)
    if axis is None:
        a = a.reshape(-1, order="F")
        axis = 0
    a = np.moveaxis(a, axis, 0)
    acc = np.zeros(a.shape[1:], dtype=f32)
    for k in range(a.shape[0]):
        acc = acc + a[k]
    return acc if acc.ndim else f32(acc)
