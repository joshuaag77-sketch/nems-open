"""The CMM's transfer schema, built from what NEMS and the AIMMS model actually exchange.

Three sources, none guessed:
  models/coal/input/coalputvars.txt   what NEMS sends the CMM (106 entries, 104 unique)
  models/coal/input/coalgetvars.txt   what NEMS expects back (157 unique)
  coal.ams, SendGlobalDataToNEMS      what the AIMMS model really writes (159 arrays); the stronger authority
Each name is looked up in EIA's variable dictionary (input/dict.txt) for its type, shape and units, and
checked against the cb2026 restart file.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from nems_open import dictionary
from nems_open.paths import UPSTREAM

COAL_DIR = UPSTREAM / "models" / "coal"
COAL_AMS = COAL_DIR / "MainProject" / "coal.ams"


@dataclass(frozen=True)
class Transfer:
    block: str
    name: str
    direction: str                               # "in" (NEMS to CMM) or "out" (CMM to NEMS)
    variable: dictionary.Variable | None         # None if the dictionary has no such variable
    aimms_dims: tuple[str, ...] = ()             # dimensions as the AIMMS writer slices them
    year_slice: bool = False                     # the writer sends one year ("globalyr"), not all 61

    @property
    def key(self) -> str:
        return f"{self.block}/{self.name}"

    @property
    def units(self) -> str:
        return self.variable.units if self.variable else ""


def _entry(block: str, name: str, direction: str, dims=(), year_slice=False) -> Transfer:
    var = dictionary.variables().get(f"{block}/{name}".lower())
    return Transfer(block.upper(), name.upper(), direction, var, tuple(dims), year_slice)


def _read_manifest(path, direction: str) -> list[Transfer]:
    seen, out = set(), []
    for line in path.read_text(encoding="latin-1").splitlines():
        m = re.match(r"\s*LABEL=\s*(\w+)\s*,\s*VAR=\s*(\w+)", line)
        if m and (m.group(1).upper(), m.group(2).upper()) not in seen:
            seen.add((m.group(1).upper(), m.group(2).upper()))
            out.append(_entry(m.group(1), m.group(2), direction))
    return out


@lru_cache(maxsize=1)
def input_manifest() -> tuple[Transfer, ...]:
    """What NEMS sends the CMM, in file order, repeats dropped (PCLELCDR appears twice)."""
    return tuple(_read_manifest(COAL_DIR / "input" / "coalputvars.txt", "in"))


@lru_cache(maxsize=1)
def output_manifest() -> tuple[Transfer, ...]:
    """What NEMS expects back from the CMM, per coalgetvars.txt."""
    return tuple(_read_manifest(COAL_DIR / "input" / "coalgetvars.txt", "out"))


def _split_block(token: str) -> tuple[str, str]:
    """MPBLK_PCLRS -> ("MPBLK", "PCLRS"): the longest prefix that is a block in the dictionary."""
    vars_ = dictionary.variables()
    parts = token.split("_")
    for i in range(len(parts) - 1, 0, -1):
        block, name = "_".join(parts[:i]), "_".join(parts[i:])
        if f"{block}/{name}".lower() in vars_:
            return block, name
    raise KeyError(f"{token} is not a dictionary variable")


@lru_cache(maxsize=1)
def written_outputs() -> tuple[Transfer, ...]:
    """The arrays SendGlobalDataToNEMS writes, from coal.ams, each with the dimensions it slices.

    "globalyr" in a dimension list marks a single-year slice of a (…, 61) array.
    """
    text = COAL_AMS.read_text(encoding="latin-1")
    start = text.index("Procedure SendGlobalDataToNEMS {")
    end = text.index("Procedure SendGlobalDataToNEMS_HistOverwrites", start)
    out, seen = [], set()
    for m in re.finditer(r"display\s*\{\s*(\w+)\s*(?:\(([^)]*)\))?\s*\}", text[start:end]):
        block, name = _split_block(m.group(1))
        if (block, name) in seen:
            continue
        seen.add((block, name))
        dims = tuple(d.strip() for d in (m.group(2) or "").split(",") if d.strip())
        out.append(_entry(block, name, "out", dims, any(d.lower() == "globalyr" for d in dims)))
    return tuple(out)


def check_against_restart(transfers, snapshot) -> dict:
    """Which transfers are in the restart file with the dictionary's shape.

    Returns {"present": n, "missing": [...], "shape_mismatch": [(key, dictionary shape, restart shape)],
    "not_in_dictionary": [...]}. A scalar the dictionary declares as (1,) and the restart stores as () counts as a match.
    """
    present, missing, mismatch, nodict = 0, [], [], []
    for t in transfers:
        if t.variable is None:
            nodict.append(t.key)
        try:
            arr = snapshot[t.key]
        except KeyError:
            missing.append(t.key)
            continue
        present += 1
        if t.variable is not None:
            want, got = dictionary.shape(t.variable), tuple(arr.shape)
            if want != got and not (want == (1,) and got == ()):
                mismatch.append((t.key, want, got))
    return {"present": present, "missing": missing, "shape_mismatch": mismatch, "not_in_dictionary": nodict}


@dataclass
class CoalInputs:
    """The arrays NEMS sends the CMM, numbers as float64 and character arrays as stored, keyed "BLOCK/NAME"."""
    arrays: dict[str, np.ndarray]
    year: int

    @classmethod
    def from_snapshot(cls, snapshot, year: int) -> "CoalInputs":
        arrays = {}
        for t in input_manifest():
            a = np.asarray(snapshot[t.key])
            arrays[t.key] = a if a.dtype.kind in "SUO" else a.astype(np.float64)       # character arrays stay as stored
        return cls(arrays, year)

    def __getitem__(self, key: str) -> np.ndarray:
        return self.arrays[key.upper()]
