"""NEMS's spreadsheet range readers (source/nemswk1.f GETRNGR, GETRNGI, GETRNGC).

A Fortran call GETRNGR('NAME', X(1:16,iy:61), ix, iy, iz) hands the routine the array
section as a block of ix*iy*iz values in column order (sequence association), and the
routine fills it from the range row by row: for each group k, each row i, each column j,
the next value of the range. When the range is smaller or larger than the block
(isetdflg/fsetxyz), the loop limits shrink the way the Fortran does; values it does not
reach keep what the array held.

`Ranges.read(arr, idx, name, ix, iy, iz)` does that on an FArray section `arr[idx]`.
"""

import numpy as np

from nems_open.xlsx_ranges import named_ranges_shaped


def inint(x: float) -> int:
    """Intel's ININT: nearest INTEGER*2, halves away from zero."""
    return int(np.trunc(x + np.copysign(0.5, x)))


class Ranges:
    def __init__(self, book, sheet: str):
        self.book, self.sheet = book, sheet
        self.r = named_ranges_shaped(book, sheet)

    def _limits(self, name, ix, iy, iz):
        _, rh, rw = self.r[name]
        onedim = rh == 1 or rw == 1
        if (iy == 1 and iz == 1) or (ix == 1 and iz == 1):
            if not onedim:
                vh, vw = 1, ix
            elif rh >= rw:
                vh, vw = max(ix, iy), 1
            else:
                vh, vw = 1, max(ix, iy)
        else:
            vh, vw = ix * iz, iy
        flag = 1 if (rh > vh or rw > vw) else 0
        if vh > rh or vw > rw:
            flag = 3 if flag else 2
        if flag in (0, 1):
            return ix, iy, iz
        if flag == 2:
            if rh == 1:
                return (rw, 1, 1) if (iy == 1 and iz == 1) else (1, rw, 1)
            x = rh if ix > rh else ix
            return x, rw, (1 if iz == 1 else rh // x)
        if rh == 1:
            return (min(iy, rw), 1, 1) if (iy != 1 or iz != 1) else (min(ix, rw), 1, 1)
        if iy == 1 and iz == 1:
            return min(ix, rw), 1, 1
        return min(ix, rh), min(iy, rw), 1

    def fill(self, name: str, block: np.ndarray, ix: int, iy: int, iz: int, kind: str = "r") -> np.ndarray:
        """block: the section's values in column order (at least ix*iy*iz of them)."""
        name = name.strip().upper()[:16]
        if name not in self.r:
            return block            # the Fortran skips a missing range
        vals = self.r[name][0]
        x, y, z = self._limits(name, ix, iy, iz)
        v = block.reshape(-1, order="F").copy()
        buf = v[:ix * iy * iz].reshape((ix, iy, iz), order="F")
        n = 0
        for k in range(z):
            for i in range(x):
                for j in range(y):
                    val = vals[n] if n < len(vals) else 0.0
                    if kind == "i":
                        buf[i, j, k] = inint(float(val))
                    elif kind == "c":
                        buf[i, j, k] = val if isinstance(val, str) else " "
                    else:
                        buf[i, j, k] = np.float32(val)
                    n += 1
        v[:ix * iy * iz] = buf.reshape(-1, order="F")
        return v.reshape(block.shape, order="F")

    def read(self, arr, idx, name: str, ix: int, iy: int, iz: int, kind: str = "r") -> None:
        """GETRNG<kind>(name, arr(idx), ix, iy, iz) on an FArray (idx as for FArray indexing)."""
        sec = np.asarray(arr[idx])
        arr[idx] = self.fill(name, sec, ix, iy, iz, kind)

    def scalar(self, name: str, kind: str = "r"):
        out = self.fill(name, np.zeros(1, dtype=np.float32 if kind == "r" else np.int32), 1, 1, 1, kind)
        return out[0]
