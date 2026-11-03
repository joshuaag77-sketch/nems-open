"""Write src/nems_open/transportation/state_layout.json: every variable TRAN's state holds.

For each name in the oracle's dumps of one year (all dump points together): its type and
bounds, and, for variables in a COMMON block, the restart-file array the oracle loads
into it before the first call ("BLOCK/var"). No values: the layout is EIA's declarations.

    python scripts/tran_state_layout.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oracle"))
import gen_oracle  # noqa: E402

from nems_open.fortran_array import FArray  # noqa: E402
from nems_open.paths import UPSTREAM  # noqa: E402
from nems_open.transportation import tran  # noqa: E402

YEAR = 31
ALT = ("angtdm", "aeusprc")       # dumped with a prefix (oracle/hooks_tran.py ALT_INCLUDES)


def main():
    inc = UPSTREAM / "includes"
    includes = gen_oracle.walk_includes(gen_oracle.MODULES["tran"]["includes"], inc)
    members = gen_oracle.common_members(inc, includes)
    by_var = {}
    for block, var in members:
        by_var.setdefault(var, set()).add(block)
    s, carry = tran.start_from_dump(YEAR)
    layout = {}
    for name in sorted(s):
        v = s[name]
        if name.startswith(("p_", "p0_", "_")):
            continue
        d = {"dtype": str(v.a.dtype)} if isinstance(v, FArray) else {"dtype": str(type(v).__name__ if not hasattr(v, "dtype") else v.dtype)}
        if isinstance(v, FArray):
            d["lb"], d["shape"] = list(v.lb), list(v.a.shape)
        prefix, _, var = name.partition("__")
        if var and prefix in ALT:
            d["restart"] = f"{prefix.upper()}/{var}"
        elif "__" not in name and name in by_var:
            blocks = sorted(b for b in by_var[name] if b.lower() not in ALT)
            if blocks:
                d["restart"] = f"{blocks[0]}/{name}"
        layout[name] = d
    out = ROOT / "src" / "nems_open" / "transportation" / "state_layout.json"
    out.write_text(json.dumps(layout, indent=0, sort_keys=True))
    cl = {routine: {k: {"dtype": str(v.a.dtype), "lb": list(v.lb), "shape": list(v.a.shape)}
                    for k, v in arrays.items() if isinstance(v, FArray)}
          for routine, arrays in carry.items() if routine != "treport"}
    (out.parent / "carry_layout.json").write_text(json.dumps(cl, indent=0, sort_keys=True))
    print(f"{len(layout)} variables, {sum('restart' in d for d in layout.values())} from the restart file -> {out}")


if __name__ == "__main__":
    main()
