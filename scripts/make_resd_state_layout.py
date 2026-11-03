"""Write src/nems_open/residential/state_layout.json: name, type, bounds and shape of every array
in RESD's state, from the residential oracle's dump indexes (every tag and year).

Run once after the residential oracle has run (the layout is EIA's declarations).
    python scripts/make_resd_state_layout.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nems_open import oracle_state  # noqa: E402


def main():
    layout = {}
    root = oracle_state.state_dir("resd")
    for idx in sorted(root.glob("*/*/index.txt")):
        for name, code, rank, bounds in oracle_state._entries(idx.read_text(encoding="latin-1")):
            if name in layout:
                continue
            d = {"dtype": code}
            if rank:
                d["lb"] = [lo for lo, _ in bounds]
                d["shape"] = [hi - lo + 1 for lo, hi in bounds]
            layout[name] = d
    out = ROOT / "src" / "nems_open" / "residential" / "state_layout.json"
    out.write_text(json.dumps(layout, indent=0, sort_keys=True))
    print(f"{len(layout)} arrays -> {out}")


if __name__ == "__main__":
    main()
