"""NumPy arrays indexed the Fortran way: 1-based, or any declared lower bound.

Ports index with the same subscripts as the Fortran, a[r, b, y], so each line can
be checked against the original. `.a` is the raw 0-based NumPy array.
"""

from operator import sub

import numpy as np


class FArray:
    def __init__(self, a: np.ndarray, lb=None):
        self.lb = tuple(lb) if lb is not None else (1,) * a.ndim
        # With every lower bound >= 0 (and the padding small) the data lives inside a padded
        # block, so Fortran subscripts index the block directly (_p[i, j, k] is
        # a[i - lb0, j - lb1, k - lb2]); `.a` is the view of the declared part. Other arrays
        # keep the plain layout.
        padded = tuple(l + n for l, n in zip(self.lb, a.shape))
        if a.ndim and min(self.lb) >= 0 and np.prod(padded, dtype=np.float64) <= 1.5 * max(a.size, 1):
            self._p = np.zeros(padded, dtype=a.dtype,
                               order="F" if a.flags.f_contiguous and not a.flags.c_contiguous else "C")
            self.a = self._p[tuple(slice(l, None) for l in self.lb)]
            self.a[...] = a
        else:
            self._p = None
            self.a = a

    @classmethod
    def zeros(cls, bounds, dtype=np.float32):
        """bounds: [(lo, hi), ...] as declared in Fortran."""
        shape = tuple(hi - lo + 1 for lo, hi in bounds)
        return cls(np.zeros(shape, dtype=dtype), [lo for lo, _ in bounds])

    def _ix(self, idx):
        if idx is Ellipsis:  # a[...]: the whole array, as numpy
            return Ellipsis
        if not isinstance(idx, tuple):
            idx = (idx,)
        return tuple(
            slice(None if i.start is None else i.start - l, None if i.stop is None else i.stop - l + 1)
            if isinstance(i, slice) else i - l
            for i, l in zip(idx, self.lb)
        )

    def __getitem__(self, idx):
        if type(idx) is int:
            return self.a[idx - self.lb[0]]
        if type(idx) is tuple:
            p = self._p
            if p is not None:
                v = p[idx]  # a full set of integer subscripts gives a scalar
                if type(v) is not np.ndarray and min(idx) >= 0:
                    return v
            try:  # fast path for integer subscripts; a slice among them raises TypeError
                return self.a[tuple(map(sub, idx, self.lb))]
            except TypeError:
                pass
        return self.a[self._ix(idx)]

    def __setitem__(self, idx, value):
        if type(idx) is int:
            self.a[idx - self.lb[0]] = value
            return
        if type(idx) is tuple:
            try:
                ix = tuple(map(sub, idx, self.lb))
            except TypeError:
                ix = self._ix(idx)
        else:
            ix = self._ix(idx)
        self.a[ix] = value

    def copy(self):
        return FArray(self.a.copy(), self.lb)
