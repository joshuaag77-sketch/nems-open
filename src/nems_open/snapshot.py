"""Read EIA's restart file: the full state of a finished NEMS run.

Arrays keep Fortran's dimension order, so QBLK/qelcm(region, year) has shape (11, 61).
Names are "BLOCK/variable", for example snapshot["COMMREP/cmtotalflspc"].
"""

from functools import cached_property
from pathlib import Path

import numpy as np

from nems_open.paths import REFERENCE_RUN


class Snapshot:
    def __init__(self, path: Path = REFERENCE_RUN):
        self.path = Path(path)

    @cached_property
    def _npz(self):
        return np.load(self.path, allow_pickle=False)

    @cached_property
    def _by_lower_name(self):
        return {k.lower(): k for k in self._npz.files}

    def __getitem__(self, name: str) -> np.ndarray:
        return self._npz[self._by_lower_name[name.lower()]]

    def names(self, contains: str = "") -> list[str]:
        return [k for k in self._npz.files if contains.lower() in k.lower()]
