"""EIA's LFMM (GAMS) fed the way NEMS feeds it: NEM_TO_LFMM1.gdx written like FILER writes it.

In NEMS, refine.f calls FILER (FUNFMT 5) with the variable list models/lfmm/input/varlistl.txt and writes every listed
array to NEM_TO_LFMM1.gdx, then runs `gams LFshell.gms`; lf_nem.gms `$Load`s the arrays by name, BLOCK_VAR, and the sets
that index them by dimension name (MNUMCR, MNUMYR, RefReg, ...). This module rebuilds that file from restart-style
arrays, with FILER's element labels (source/filer.f, the DIM/DIMD records of input/dict.txt):

  - DIMD n <text> records name element n: "NN_<text>", spaces turned to underscores, NN zero-padded to the
    dimension size's digits ("09_Pacific", "11_United_States"). The text is read from column 27, as FILER's
    format (1X,A3,A1,1X,A6,I6,8X,A) does.
  - DIMD 0 <first> records number the elements from <first>: "1990_MNUMYR", "1991_MNUMYR", ...
  - Other dimensions: "N_<DIM>" with N padded to the size's digits ("01_MNUMPR" .. "10_MNUMPR").
  - A numeric dimension in a declaration, (57,...), becomes a dimension named M57 with labels "01_M57" ...
  - FILER names at most FMaxDims - 1 = 100 elements of a dimension (fdict); later elements get no name. Zero values
    are not written (WriteGDXElement), so this only matters where an array is non-zero beyond element 100.

Writing needs GAMS's GDX library: run the write step with the GAMS venv's Python (gams.transfer), see write_gdx.
"""

import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

from nems_open import dictionary
from nems_open.paths import INPUT, UPSTREAM

LFMM_DIR = Path(UPSTREAM) / "models" / "lfmm"
FMAXDIMS = 101          # includes/fdict: FMaxDims
LABEL_LEN = 25          # FDimStrs is CHARACTER*25: longer labels are cut ("11_Petrochemical_feedstoc")
GAMS_SYSDIR = Path.home() / "dev" / "gams-venv" / "Lib" / "site-packages" / "gamspy_base"
GAMS_PYTHON = Path.home() / "dev" / "gams-venv" / "Scripts" / "python.exe"


def _width(n: int) -> int:
    return 1 if n <= 9 else 2 if n <= 99 else 3 if n <= 999 else 4


@lru_cache(maxsize=1)
def dim_labels() -> dict[str, list[str]]:
    """Element labels of every dict.txt dimension, by FILER's rules."""
    sizes = dictionary.sizes()
    named: dict[str, dict[int, str]] = {}
    numbered: dict[str, int] = {}
    for line in (INPUT / "dict.txt").read_text(encoding="latin-1").splitlines():
        if not line.startswith(" DIMD"):
            continue
        name = line[6:12].strip()
        i = int(line[12:18])
        if i == 0:
            numbered[name] = int(line[19:23])
        else:
            named.setdefault(name, {})[i] = re.sub(" ", "_", line[26:].rstrip())
    out = {}
    for d, n in sizes.items():
        w = _width(n)
        if d in numbered:
            first = numbered[d]
            wl = _width(n + first - 1)
            out[d] = [f"{first + k:0{wl}d}_{d}" for k in range(n)]
        elif d in named:
            out[d] = [f"{k:0{w}d}_{named[d].get(k, '')}"[:LABEL_LEN] for k in range(1, n + 1)]
        else:
            out[d] = [f"{k:0{w}d}_{d}" for k in range(1, n + 1)]
    return out


def labels(dim: str) -> list[str]:
    """Labels of one dimension; a number n stands for an unnamed dimension Mn."""
    if dim.isdigit():
        n = int(dim)
        if n > FMAXDIMS:   # FILER numbers dimensions longer than FMaxDims plainly: M102 is "001" .. "102"
            return [f"{k:0{_width(n)}d}" for k in range(1, n + 1)]
        return [f"{k:0{_width(n)}d}_M{n}" for k in range(1, n + 1)]
    return dim_labels()[dim]


def dim_name(dim: str) -> str:
    return f"M{int(dim)}" if dim.isdigit() else dim


@lru_cache(maxsize=1)
def varlist() -> list[dictionary.Variable]:
    """The arrays refine.f writes to NEM_TO_LFMM1.gdx: models/lfmm/input/varlistl.txt (VAR=ALL takes the whole block)."""
    allv = dictionary.variables()
    out, seen = [], set()
    for line in (LFMM_DIR / "input" / "varlistl.txt").read_text(encoding="latin-1").splitlines():
        m = re.match(r"\s*LABEL=\s*(\w+)\s*,\s*VAR=\s*(\w+)", line, re.I)
        if not m:
            continue
        block, var = m.group(1).upper(), m.group(2).upper()
        names = [v for v in allv.values() if v.block.upper() == block] if var == "ALL" else \
            [allv[f"{block}/{var}".lower()]] if f"{block}/{var}".lower() in allv else []
        for v in names:
            if v.key.upper() not in seen and v.type != "C":
                seen.add(v.key.upper())
                out.append(v)
    return out


def records(var: dictionary.Variable, arr) -> tuple[list[str], list[tuple]]:
    """(dimension names, [(label, ..., value)]) for one array, zeros skipped, as WriteGDXElement writes it.
    Trailing dimensions of size 1 are dropped (FILER counts dimensions up to the last one above 1)."""
    a = np.asarray(arr, dtype=np.float64)
    dims = [d for d in var.dims]
    # FILER's dimension count is the position of the last dimension above 1; size-1 dimensions before it stay
    last = max([k for k in range(a.ndim) if a.shape[k] > 1], default=-1)
    keep = list(range(last + 1))
    names = [dim_name(dims[k]) for k in keep] if a.ndim == len(dims) else [f"D{k}" for k in keep]
    labs = [labels(dims[k]) if a.ndim == len(dims) else [str(i + 1) for i in range(a.shape[k])] for k in keep]
    rows = []
    for idx in zip(*np.nonzero(a)):
        if any(idx[k] >= FMAXDIMS - 1 and not dims[k].isdigit() and len(labs[j]) >= FMAXDIMS
               for j, k in enumerate(keep)):
            pass   # FILER leaves elements beyond 100 unnamed; such values are rare and still written here
        rows.append(tuple(labs[j][idx[k]] for j, k in enumerate(keep)) + (float(a[idx]),))
    return names, rows


def to_npz(arrays: dict, year: int, itr: int, fcrl: int, ncrl: int, cycle: int, path: Path) -> Path:
    """Everything needed for NEM_TO_LFMM1.gdx in one npz (labels and records), for the GAMS venv to write."""
    import pickle
    payload = {"sets": {}, "params": {}, "scalars": {}}
    control = {"NCNTRL_CURCALYR": year, "NCNTRL_CURITR": itr, "NCNTRL_FCRL": fcrl, "NCNTRL_NCRL": ncrl,
               "CYCLEINFO_CURIRUN": cycle}
    used = set()
    for v in varlist():
        sym = f"{v.block}_{v.name}".upper()
        if sym in control:
            payload["scalars"][sym] = float(control[sym])
            continue
        key = v.key.upper()
        if key not in arrays:
            continue
        a = np.asarray(arrays[key])
        if a.size == 1:
            payload["scalars"][sym] = float(a.reshape(-1)[0])
            continue
        names, rows = records(v, a)
        payload["params"][sym] = (names, rows, v.description)
        used.update(n for n in names)
    for d in sorted(used | set(dictionary.sizes())):
        try:
            payload["sets"][d] = labels(d[1:]) if re.fullmatch(r"M\d+", d) and d not in dictionary.sizes() else labels(d)
        except KeyError:
            continue
    with open(path, "wb") as f:
        pickle.dump(payload, f)
    return Path(path)


def write_gdx(payload_path: Path, gdx_path: Path) -> None:
    """Run under the GAMS venv's Python: the payload as a GDX file (sets, scalars, parameters with relaxed domains)."""
    import pickle
    import pandas as pd
    import gams.transfer as gt
    with open(payload_path, "rb") as f:
        p = pickle.load(f)
    m = gt.Container(system_directory=str(GAMS_SYSDIR))
    for name, labs in p["sets"].items():
        gt.Set(m, name, records=pd.DataFrame({"uni": labs}))
    for name, v in p["scalars"].items():
        gt.Parameter(m, name, records=v)
    for name, (dims, rows, text) in p["params"].items():
        df = pd.DataFrame(rows, columns=[f"d{k}" for k in range(len(dims))] + ["value"]) if rows else None
        gt.Parameter(m, name, domain=dims, records=df, description=(text or "")[:255])   # "*" = universe
    m.write(str(gdx_path))


def read_gdx(gdx_path: Path, out_path: Path, names=None) -> None:
    """Run under the GAMS venv's Python: parameters of a GDX file (all, or `names`) to a pickle of
    {name: {label tuple: value}}, for the project Python to read (read_outputs)."""
    import pickle
    import gams.transfer as gt
    m = gt.Container(str(gdx_path), system_directory=str(GAMS_SYSDIR))
    out = {}
    for name, sym in m.data.items():
        if names and name.upper() not in {n.upper() for n in names}:
            continue
        if not isinstance(sym, gt.Parameter):
            continue
        r = sym.records
        if r is None:
            out[name.upper()] = {}
        elif sym.dimension == 0:
            out[name.upper()] = {(): float(r.iloc[0, -1])}
        else:
            out[name.upper()] = {tuple(str(x) for x in row[:-1]): float(row[-1]) for row in r.itertuples(index=False)}
    with open(out_path, "wb") as f:
        pickle.dump(out, f)


def read_outputs(gdx_path: Path, names=None) -> dict:
    """LFMM's output GDX (LFMM_to_NEMS.gdx) as {name: {label tuple: value}}, through the GAMS venv."""
    import os
    import pickle
    import subprocess
    import tempfile
    from nems_open.paths import REPO_ROOT
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.pkl"
        args = [str(GAMS_PYTHON), "-m", "nems_open.lfmm.gams_io", "read", str(gdx_path), str(out)] + list(names or [])
        subprocess.run(args, check=True, env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")})
        with open(out, "rb") as f:
            return pickle.load(f)


if __name__ == "__main__":
    if sys.argv[1] == "write":
        write_gdx(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1] == "read":
        read_gdx(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4:] or None)

