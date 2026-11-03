"""Write src/nems_open/commercial/state_layout.json: name, type, bounds and shape of every array in COMM's state.

Run once after the oracle has run (the layout is EIA's declarations, so it only changes with the source).
    python scripts/make_state_layout.py
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nems_open import oracle_state  # noqa: E402
from nems_open.commercial import comm  # noqa: E402
from nems_open.fortran_array import FArray  # noqa: E402

Y = 30


def main():
    layout = {}
    tags = ["sd_in", "sd_out", "tc_out", "cn_out", "bm_out", "bm_pre", "dg_out", "tc_pre"]
    for tag in tags:
        if not oracle_state.available(tag, Y):
            continue
        for k, v in oracle_state.load(tag, Y).items():
            if k in layout:
                continue
            if isinstance(v, FArray):
                layout[k] = {"dtype": v.a.dtype.str, "lb": list(v.lb), "shape": list(v.a.shape)}
            else:
                layout[k] = {"dtype": np.asarray(v).dtype.str}
    out = ROOT / "src" / "nems_open" / "commercial" / "state_layout.json"
    out.write_text(json.dumps(layout, indent=0, sort_keys=True))
    print(f"{len(layout)} arrays -> {out}")


if __name__ == "__main__":
    main()
