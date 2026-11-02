"""Parameters shared by the residential routines (parametr, resdrep, MODULE R_)."""

import numpy as np

f32 = np.float32

BASEYR = 1990
ENDYR = 2050
RECSYEAR = 2020
LASTSTEOYR = 2026
MNUMYR = 61
MNUMCR = 11
MNUMBLDG = 3
MNUMFUEL = 5  # rtek: gas, electricity, distillate/kerosene, propane, wood
NUM_DIV = MNUMCR - 2  # census divisions 1-9
COSTTRSW = 0  # rtek PARAMETER: 0 = menu costs, EQCOST trend off


_POWI = {}


def powi(x, m: int):
    """REAL*4 ** INTEGER as gfortran evaluates it (libgcc __powisf2): repeated
    squaring in single precision, so the last bit matches. Memoized on the
    argument's bit pattern (so -0.0 and 0.0 stay apart); the routines ask for the
    same few powers thousands of times a year."""
    x = f32(x)
    key = (x.tobytes(), m)
    y = _POWI.get(key)
    if y is None:
        if len(_POWI) > 500_000:
            _POWI.clear()
        y = _POWI[key] = _powi(x, m)
    return y


def _powi(x, m: int):
    x = f32(x)
    n = -m if m < 0 else m
    y = x if n % 2 else f32(1.0)
    n >>= 1
    while n:
        x = f32(x * x)
        if n % 2:
            y = f32(y * x)
        n >>= 1
    return f32(1.0) / y if m < 0 else y


def expf(x):
    """REAL*4 EXP as the oracle's libm computes it: correctly rounded, which
    double precision rounded once to single reproduces. NumPy's float32 exp can
    be an ulp or two off."""
    return f32(np.exp(np.float64(x)))


def powf(x, y):
    """REAL*4 ** REAL*4, rounded once from double precision (see expf)."""
    return f32(np.power(np.float64(x), np.float64(y)))


def logf(x):
    """REAL*4 LOG, rounded once from double precision (see expf)."""
    return f32(np.log(np.float64(x)))
