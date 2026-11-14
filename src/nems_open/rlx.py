"""Reader for EIA's older restart format (AEO2025): a FILER unformatted sequential file.

The AEO2026 `restart.rlx` is a numpy archive. The AEO2025 one is not: it is a Fortran unformatted
sequential file with big-endian 4-byte record markers, in pairs of records: an 80-byte label
(` LABEL=MPBLK,VAR=PELRS,FORMAT=14F10.3`) and the variable's values as raw big-endian 4-byte numbers
(reals as float32, integers as int32, characters as bytes). This reads the bytes only; nothing in the file is executed.

Shapes come from the variable dictionary (`input/dict.txt`) of the same release, in Fortran order, so a
variable declared (MNUMCR, MNUMYR) has shape (11, 61), as in the 2026 archive.
"""

import re
import struct
from pathlib import Path

import numpy as np

from nems_open import dictionary

LABEL = re.compile(rb"LABEL=([^,]+),VAR=([^,]+),FORMAT=(\S+)")


def records(path: Path):
    data = Path(path).read_bytes()
    pos = 0
    while pos < len(data):
        (n,) = struct.unpack(">I", data[pos:pos + 4])
        yield data[pos + 4: pos + 4 + n]
        pos += 8 + n


def read(path: Path, dict_path: Path) -> dict[str, np.ndarray]:
    """{"BLOCK/NAME": array} for every variable in the file; shapes from `dict_path`.

    A variable the dictionary does not know, or whose size does not match, comes back flat.
    """
    variables = dictionary.variables(dict_path)
    sizes = dictionary.sizes(dict_path)
    out = {}
    it = records(path)
    for label in it:
        m = LABEL.search(label)
        if not m:
            raise ValueError(f"expected a label record, got {label[:40]!r}")
        block, name = m.group(1).decode(), m.group(2).decode()
        body = next(it)
        fmt = m.group(3).decode()
        var = variables.get(f"{block}/{name}".lower())
        if var is not None and var.type == "C":
            arr = np.frombuffer(body, dtype="S1")
        elif "I" in fmt.upper().split(".")[0][-3:] or (var is not None and var.type == "I"):
            arr = np.frombuffer(body, dtype=">i4").astype(np.int32)
        else:
            arr = np.frombuffer(body, dtype=">f4").astype(np.float32)
        if var is not None:
            try:
                shape = dictionary.shape(var, extra=sizes)
                if int(np.prod(shape)) == arr.size:
                    arr = arr.reshape(shape, order="F")
            except KeyError:
                pass
        out[f"{block}/{name}"] = arr
    return out
