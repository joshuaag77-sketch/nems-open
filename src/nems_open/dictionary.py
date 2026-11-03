"""EIA's FILER dictionary (input/dict.txt): the layout of every common block NEMS passes between modules.

One record per variable: block, name, type, byte length, dimension names, then a quantity type, units,
fuel, sector and a description. Dimension names resolve to sizes through the file's DIM records.
Arrays in the restart file keep Fortran's dimension order, so a variable declared (MNUMCR,MNUMYR) has
shape (11, 61) there.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from nems_open.paths import INPUT


@dataclass(frozen=True)
class Variable:
    block: str
    name: str
    type: str                    # R real, I integer, C character
    length: int                  # bytes (characters for C)
    dims: tuple[str, ...]        # dimension names as declared, e.g. ("MNUMCR", "MNUMYR")
    quantity: str                # QUNTY, PRICE, RATE, LEVEL, ...
    units: str
    fuel: str
    sector: str
    description: str

    @property
    def key(self) -> str:
        return f"{self.block}/{self.name}"


@lru_cache(maxsize=1)
def _parse(path: str):
    lines = Path(path).read_text(encoding="latin-1").splitlines()
    sizes, variables = {}, {}
    block = ""
    for line in lines:
        if not line.strip() or line[0] == "*":
            continue
        head = line.lstrip().split(None, 1)[0]
        if head == "DIM":
            m = re.match(r"\s*DIM\s+(\S+)\s+(\d+)", line)
            if m:
                sizes[m.group(1)] = int(m.group(2))
            continue
        if head in ("DIMD", "ATT"):
            continue
        # Fixed columns: block 2-17, name 19-34, type 36, length 38-41, number of dimensions 43.
        b, name, ty = line[1:17].strip(), line[18:34].strip(), line[35:36]
        if ty not in ("R", "I", "C") or not name:
            continue                                   # a block header line ("TYPE UNITS FUEL SECTOR")
        block = b or block
        m = re.match(r"\s*(\d+)\s+(\d)\s*(\(([^)]*)\))?\s*(.*)$", line[36:])
        if not m:
            continue
        dims = tuple(d.strip() for d in (m.group(4) or "").split(",") if d.strip())
        rest = m.group(5).split(None, 4)
        rest += [""] * (5 - len(rest))
        variables[f"{block}/{name}".lower()] = Variable(block, name, ty, int(m.group(1)), dims, *rest)
    return sizes, variables


def sizes(path: Path | None = None) -> dict[str, int]:
    """Dimension name -> size (the DIM records)."""
    return dict(_parse(str(path or INPUT / "dict.txt"))[0])


def variables(path: Path | None = None) -> dict[str, Variable]:
    """Every variable, keyed by lowercase "BLOCK/name"."""
    return _parse(str(path or INPUT / "dict.txt"))[1]


def lookup(block: str, name: str) -> Variable:
    return variables()[f"{block}/{name}".lower()]


def shape(var: Variable, extra: dict[str, int] | None = None) -> tuple[int, ...]:
    """Fortran-order shape. A dimension is a DIM name, a number, or a sum like "MNUMYR+10"; `extra` adds names."""
    table = {**sizes(), **(extra or {})}

    def size(d: str) -> int:
        if d in table:
            return table[d]
        if re.fullmatch(r"\d+", d):
            return int(d)
        if re.fullmatch(r"\w+\s*[+-]\s*\w+", d):
            a, op, b = re.match(r"(\w+)\s*([+-])\s*(\w+)", d).groups()
            av, bv = size(a), size(b)
            return av + bv if op == "+" else av - bv
        raise KeyError(f"unknown dimension {d!r} in {var.key}")

    return tuple(size(d) for d in var.dims)
