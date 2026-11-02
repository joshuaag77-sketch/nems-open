"""Pack oracle state dumps into compressed .npz files (about 50x smaller, and no slower to load).

    python scripts/pack_oracle.py comm                # pack, keep the raw folders
    python scripts/pack_oracle.py comm --delete-raw   # pack, verify, then delete each raw folder

Each <tag>/<year>/ folder becomes <tag>/<year>.npz. oracle_state.load reads either form.
A raw folder is deleted only after its .npz reloads to identical arrays.
"""

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nems_open import oracle_state  # noqa: E402


def pack_one(folder: Path) -> Path:
    index = (folder / "index.txt").read_text(encoding="latin-1")
    arrays = {}
    for line in index.splitlines():
        parts = line.split()
        if parts:
            arrays[parts[0]] = np.fromfile(folder / f"{parts[0]}.bin", dtype=np.dtype(parts[1]))
    out = folder.with_suffix(".npz")                    # <year>.npz next to <year>/
    tmp = folder.parent / f"{folder.name}.tmp.npz"
    np.savez_compressed(tmp, __index__=np.str_(index), **arrays)
    with np.load(tmp) as z:
        assert str(z["__index__"]) == index and all(np.array_equal(z[k], v) for k, v in arrays.items()), folder
    tmp.replace(out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("module")
    ap.add_argument("--delete-raw", action="store_true")
    a = ap.parse_args()
    state = oracle_state.state_dir(a.module)
    raw = packed = 0
    for folder in sorted(p.parent for p in state.glob("*/*/index.txt")):
        size = sum(f.stat().st_size for f in folder.iterdir())
        out = pack_one(folder)
        raw, packed = raw + size, packed + out.stat().st_size
        if a.delete_raw:
            shutil.rmtree(folder)
    print(f"{a.module}: {raw / 1e9:.2f} GB raw -> {packed / 1e9:.3f} GB packed" + (" (raw deleted)" if a.delete_raw else ""))


if __name__ == "__main__":
    main()
