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


def powi(x, m: int):
    """REAL*4 ** INTEGER as gfortran evaluates it (libgcc __powisf2): repeated
    squaring in single precision, so the last bit matches."""
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
