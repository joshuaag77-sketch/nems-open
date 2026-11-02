"""Print oracle dump size per module (raw and packed) and free disk space.

    python scripts/disk_report.py
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nems_open import oracle_state  # noqa: E402
from nems_open.paths import REPO_ROOT  # noqa: E402


def size(root: Path):
    """(raw bytes, packed bytes) under root."""
    raw = packed = 0
    if root.is_dir():
        for f in root.rglob("*"):
            if f.is_file():
                if f.suffix == ".npz":
                    packed += f.stat().st_size
                else:
                    raw += f.stat().st_size
    return raw, packed


def gb(n):
    return f"{n / 1e9:7.2f} GB"


def main():
    print(f"shared cache: {oracle_state.ORACLE_DIR}  (NEMS_ORACLE_DIR)")
    print(f"{'module':8}{'where':28}{'raw':>12}{'packed':>12}")
    for module, run in oracle_state.RUN_DIRS.items():
        for where, root in (("shared cache", oracle_state.ORACLE_DIR / module / "out"),
                            ("this clone (oracle/" + run + ")", REPO_ROOT / "oracle" / run / "out")):
            if root.is_symlink() or (root.exists() and root.is_junction()):
                continue                                  # a link into the cache: counted once, above
            raw, packed = size(root)
            if raw or packed:
                print(f"{module:8}{where:28}{gb(raw):>12}{gb(packed):>12}")
    for label, path in (("cache drive", oracle_state.ORACLE_DIR if oracle_state.ORACLE_DIR.exists() else Path.home()),
                        ("clone drive", REPO_ROOT)):
        u = shutil.disk_usage(path)
        print(f"free on {label} ({path.anchor}): {gb(u.free)} of {gb(u.total)}")


if __name__ == "__main__":
    main()
