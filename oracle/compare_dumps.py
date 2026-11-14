"""Compare two oracle dump folders array by array: python compare_dumps.py <a>/state <b>/state [tag ...]

A correct Linux (WSL) build writes the same bytes as the Windows build. Reports, per tag and year,
how many arrays differ and the largest relative difference; exits 1 if any array differs in more than
the last bit (set --bits 0 to demand identical bytes).
"""

import sys
from pathlib import Path

import numpy as np


def load(folder: Path) -> dict:
    out = {}
    for line in (folder / "index.txt").read_text(encoding="latin-1").splitlines():
        parts = line.split()
        if parts:
            out[parts[0]] = np.fromfile(folder / f"{parts[0]}.bin", dtype=np.dtype(parts[1]))
    return out


def main(argv):
    bits = 1
    if "--bits" in argv:
        i = argv.index("--bits")
        bits = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    a, b = Path(argv[1]), Path(argv[2])
    tags = argv[3:] or sorted(p.name for p in a.iterdir() if p.is_dir())
    worst = 0
    for tag in tags:
        for ydir in sorted((a / tag).iterdir()):
            if not (ydir / "index.txt").exists() or not (b / tag / ydir.name / "index.txt").exists():
                continue
            x, y = load(ydir), load(b / tag / ydir.name)
            diff = [k for k in x if k not in y or x[k].shape != y[k].shape or x[k].tobytes() != y[k].tobytes()]
            rel = 0.0
            ulps = 0
            for k in diff:
                if k in y and x[k].shape == y[k].shape and x[k].dtype.kind == "f":
                    xf, yf = x[k].astype(np.float64), y[k].astype(np.float64)
                    rel = max(rel, float((np.abs(xf - yf) / np.maximum(np.abs(xf), 1e-30)).max()))
                    ints = (x[k].view(np.int32 if x[k].itemsize == 4 else np.int64).astype(np.int64)
                            - y[k].view(np.int32 if y[k].itemsize == 4 else np.int64).astype(np.int64))
                    ulps = max(ulps, int(np.abs(ints).max()))
                else:
                    ulps = max(ulps, 99)
            worst = max(worst, ulps)
            print(f"{tag}/{ydir.name}: {len(diff)} of {len(x)} arrays differ, max rel {rel:.2e}, max {ulps} bits apart")
    print("identical" if worst == 0 else f"worst: {worst} units in the last place")
    return 0 if worst <= bits else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
