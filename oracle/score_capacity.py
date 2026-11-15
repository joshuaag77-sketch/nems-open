"""Capacity by region and fuel from the AIMMS-coupled oracle's full run, scored against EIA's restart.

Run:  python oracle/score_capacity.py <dump>/state/final/61 [out.md]

The oracle runs EIA's own EMM (Fortran plus the AIMMS ECP, EFD and ReStore models) for 2020-2050. Its final dump
holds the restart block UDATOUT, so its year-end capacity (ucap<prefix>u/n) is read exactly as the scorecard reads
EIA's restart (nems_open.emm.capacity_regions): same fuel groups, 5% tolerance, 0.5 GW floor, 25 regions.
"""

import sys
from pathlib import Path

import numpy as np

from nems_open.emm import capacity_regions as cr
from nems_open.snapshot import Snapshot


class DumpSnapshot:
    """The restart arrays the scorecard reads, from an oracle dump folder, in the restart's shape."""

    def __init__(self, folder: Path, eia: Snapshot):
        self.folder, self.eia = folder, eia
        self.index = {p[0].lower(): p[1] for p in (l.split() for l in (folder / "index.txt").read_text().splitlines()) if p}

    def __getitem__(self, key):
        block, name = key.split("/")
        if name.lower() not in self.index:
            raise KeyError(key)
        shape = np.asarray(self.eia[key]).shape
        flat = np.fromfile(self.folder / f"{name.lower()}.bin", dtype=np.dtype(self.index[name.lower()]))
        return flat.reshape(shape, order="F" if len(shape) > 1 and self._fortran(key, flat, shape) else "C")

    def _fortran(self, key, flat, shape) -> bool:
        # The dump is column-major (Fortran); the restart reader may give either layout. 2020's history is the same
        # in both runs, so pick the order that matches it.
        e = np.nan_to_num(np.asarray(self.eia[key], dtype=float))
        f, c = flat.reshape(shape, order="F"), flat.reshape(shape, order="C")
        return np.abs(np.nan_to_num(f.astype(float)) - e).sum() <= np.abs(np.nan_to_num(c.astype(float)) - e).sum()


class Year:
    def __init__(self, year, capacity):
        self.year, self.capacity = year, capacity


def main(folder: str, out: str | None = None):
    eia = Snapshot()
    snap = DumpSnapshot(Path(folder), eia)
    # One model group per fuel, holding the oracle's fuel total (read the way cr._eia reads EIA's restart).
    results = [Year(y, {mg[0]: cr._eia(snap, y, f) for f, (_, mg) in cr.FUELS.items()}) for y in cr.YEARS]
    fuels = {f: (rg, mg[:1]) for f, (rg, mg) in cr.FUELS.items()}
    saved, cr.FUELS = cr.FUELS, fuels
    try:
        cmp = cr.compare(eia, results)
        text = ("Oracle (EIA's EMM in the WSL oracle, ECP/EFD/ReStore in AIMMS) / EIA cb2026 restart\n\n"
                + cr.table(cmp) + "\n\nLargest gaps in 2050:\n" + cr.worst(cmp, 2050) + "\n\n" + cr.national(cmp))
    finally:
        cr.FUELS = saved
    print(text)
    if out:
        Path(out).write_text(text + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
