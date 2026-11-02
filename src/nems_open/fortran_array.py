"""NumPy arrays indexed the Fortran way: 1-based, or any declared lower bound.

Ports index with the same subscripts as the Fortran, a[r, b, y], so each line can
be checked against the original. `.a` is the raw 0-based NumPy array.
"""

import numpy as np


class FArray:
    def __init__(self, a: np.ndarray, lb=None):
        self.a = a
        self.lb = tuple(lb) if lb is not None else (1,) * a.ndim

    @classmethod
    def zeros(cls, bounds, dtype=np.float32):
        """bounds: [(lo, hi), ...] as declared in Fortran."""
        shape = tuple(hi - lo + 1 for lo, hi in bounds)
        return cls(np.zeros(shape, dtype=dtype), [lo for lo, _ in bounds])

    def _ix(self, idx):
        if not isinstance(idx, tuple):
            idx = (idx,)
        return tuple(
            slice(None if i.start is None else i.start - l, None if i.stop is None else i.stop - l + 1)
            if isinstance(i, slice) else i - l
            for i, l in zip(idx, self.lb)
        )

    def __getitem__(self, idx):
        return self.a[self._ix(idx)]

    def __setitem__(self, idx, value):
        self.a[self._ix(idx)] = value

    def copy(self):
        return FArray(self.a.copy(), self.lb)
