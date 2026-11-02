"""Point an oracle's run/out at the shared cache (NEMS_ORACLE_DIR, default ~/dev/oracle-cache).

    python cache.py comm      # or resd

Creates <cache>/<module>/out and makes run*/out a junction (symlink off Windows) to it, so the
Fortran, which writes to out/ relative to its run folder, fills the shared copy. An existing real
run*/out folder is left alone: nothing is moved or deleted.
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("NEMS_ORACLE_DIR", Path.home() / "dev" / "oracle-cache"))
RUN = {"comm": "run", "resd": "run_resd"}


def link_out(module: str) -> Path:
    target = CACHE / module / "out"
    target.mkdir(parents=True, exist_ok=True)
    link = HERE / RUN.get(module, f"run_{module}") / "out"
    link.parent.mkdir(exist_ok=True)
    if link.is_symlink() or (os.name == "nt" and link.is_junction()):
        return target
    if link.exists():
        print(f"cache: {link} is a real folder, leaving it ({module} dumps stay in this clone)")
        return link
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, stdout=subprocess.DEVNULL)
    else:
        link.symlink_to(target, target_is_directory=True)
    print(f"cache: {link} -> {target}")
    return target


if __name__ == "__main__":
    link_out(sys.argv[1] if len(sys.argv) > 1 else "comm")
