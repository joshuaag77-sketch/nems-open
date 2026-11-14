"""Make a Linux-friendly view of EIA's upstream tree for the oracle builds under WSL.

    python3 wsl_prepare.py <upstream> <view>

EIA's code was written for Windows and Intel Fortran, which ignore case in file names and accept
CRLF line endings. On Linux:
  * INCLUDE 'PARAMETR' must find the file `parametr`: the view's `includes` folder holds every include
    file under its own lower-case name and under each spelling any source uses, with LF endings.
  * every other top-level folder of the upstream tree is a symlink in the view, and the view's path
    has no spaces, so the compiler's -I and the run folder's file list never see one (the upstream
    checkout itself may sit under "3. AI Projects").
"""

import os
import re
import sys
from pathlib import Path

INCLUDE = re.compile(r"^\s*include\s*['\"]([^'\"]+)['\"]", re.I | re.M)


def spellings(upstream: Path) -> dict:
    """{lower-case include name: set of spellings used by any source or include}."""
    seen = {}
    for folder in ("source", "includes"):
        for f in (upstream / folder).iterdir():
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="latin-1")
            except OSError:
                continue
            for m in INCLUDE.finditer(text):
                seen.setdefault(m.group(1).lower(), set()).add(m.group(1))
    return seen


def prepare(upstream: Path, view: Path) -> None:
    upstream, view = Path(os.path.abspath(upstream)), Path(view)
    view.mkdir(parents=True, exist_ok=True)
    for entry in upstream.iterdir():
        if entry.name == "includes" or entry.name.startswith(".") or os.name == "nt":   # (links need Linux)
            continue
        link = view / entry.name
        if link.is_symlink() or link.exists():
            if link.is_symlink() and Path(os.readlink(link)) == entry:
                continue
            link.unlink()
        link.symlink_to(entry, target_is_directory=entry.is_dir())
    inc = view / "includes"
    if inc.is_symlink():
        inc.unlink()
    inc.mkdir(exist_ok=True)
    used = spellings(upstream)
    n = 0
    for f in sorted((upstream / "includes").iterdir()):
        if not f.is_file():
            continue
        data = f.read_bytes().replace(b"\r\n", b"\n")
        for name in {f.name, f.name.lower()} | used.get(f.name.lower(), set()):
            target = inc / name
            if not target.exists() or target.read_bytes() != data:
                target.write_bytes(data)
            n += 1
    print(f"wsl_prepare: {n} include files in {inc}, {sum(1 for _ in view.iterdir()) - 1} links")


if __name__ == "__main__":
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
