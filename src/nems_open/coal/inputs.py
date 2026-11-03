"""The CMM's input files, read into named parameters.

NEMS tells the AIMMS model which files to read through scedes keys (CLCDSRN, CLFLAGSN, ...), which
`prenems_aimms.write_runval_cmm` writes to cl_runval.txt. For cb2026 they are the files under
models/coal/input, listed in scedes/scedes.cb2026.csv. This module reads those files with the
composite-table parser and the declarations in coal.ams.

    data = load()
    data.param("cl_qty")                 # {(keys…): value}
    data.sets["dreg"]                    # elements in the order the files list them

What is read:  every file the scedes file names under models/coal/input (33), the plant-unit list
(coalunits.txt, a different format), and the files beside the project (emmbench.txt, coalmapping.txt).
What is not: the AIMMS case files (Cases/CMMLagData.data and global_data.data, binary), so the
lagged state they hold is named in `LAG_STATE` but not loaded; see docs/coal_inputs.md.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from nems_open.coal import aimms_data as ad
from nems_open.coal.state import COAL_DIR
from nems_open.paths import UPSTREAM

INPUT_DIR = COAL_DIR / "input"


@lru_cache(maxsize=None)
def selected_files(scenario: str = "cb2026") -> dict[str, Path]:
    """{SCEDES key: path} for the coal files a scenario's scedes file selects (CLxxxN and ICMMCOMMODITYMAPN)."""
    out = {}
    text = (UPSTREAM / "scedes" / f"scedes.{scenario}.csv").read_text(encoding="latin-1")
    for line in text.splitlines():
        key, _, rest = line.partition(",")
        path = rest.split(",")[0].strip()
        if re.fullmatch(r"(CL\w+N|ICMMCOMMODITYMAPN)", key.strip()) and path:
            # Paths are relative to the AIMMS project folder, models/coal/MainProject.
            out[key.strip()] = (COAL_DIR / "MainProject" / path).resolve() if path.startswith("..") else Path(path.replace("$NEMS", str(UPSTREAM)))
    return out


@dataclass
class Param:
    name: str
    domain: tuple[str, ...]
    data: dict = field(default_factory=dict)          # key tuple -> value (blank cells are absent)
    sources: list = field(default_factory=list)       # file names that define it

    def __len__(self):
        return len(self.data)


@dataclass
class CoalData:
    params: dict[str, Param] = field(default_factory=dict)
    sets: dict[str, list] = field(default_factory=dict)         # set name -> elements in order of first appearance
    assignments: dict[str, object] = field(default_factory=dict)
    flags: dict[str, object] = field(default_factory=dict)
    unresolved: list = field(default_factory=list)             # (file, header, why)
    duplicates: list = field(default_factory=list)             # (parameter, key, first value, later value)
    tables: dict[str, list] = field(default_factory=dict)      # file name -> raw tables, for traceability

    def param(self, name: str) -> dict:
        return self.params[name.lower()].data


def _add_set_element(sets: dict, set_name: str, element):
    seen = sets.setdefault(set_name, [])
    if element not in seen:
        seen.append(element)


def _domain_columns(domain, keys: dict, decl) -> list | None:
    """Table column for each index of a parameter's domain: the column with that index name, else an unused
    column holding an index of the same set (the model declares aliases such as VesselClass and vclass)."""
    used, cols = set(), []
    for ix in domain:
        if ix in keys and keys[ix] not in used:
            pos = keys[ix]
        else:
            same = [p for h, p in keys.items() if p not in used and decl.root(h) == decl.root(ix)]
            if not same:
                return None
            pos = same[0]
        used.add(pos)
        cols.append(pos)
    return cols


def load_file(path: Path, data: CoalData) -> None:
    decl = ad.declarations()
    parsed = ad.parse_file(path)
    data.assignments.update({k: v for k, v in parsed.assignments.items()})
    data.tables[path.name] = parsed.tables
    for t in parsed.tables:
        keys = {}                                                  # index name -> column position
        for pos, h in enumerate(t.headers):
            if h in decl.index_set:
                keys[h] = pos
            elif h in decl.sets:
                keys[h] = pos
        for pos, h in enumerate(t.headers):
            if h in keys:
                continue
            dom = decl.domain.get(h)
            if dom is None:
                data.unresolved.append((path.name, h, "not declared"))
                continue
            cols = _domain_columns(dom, keys, decl)
            if cols is None:
                data.unresolved.append((path.name, h, f"domain {dom} not among the table's keys {tuple(keys)}"))
                continue
            p = data.params.setdefault(h, ad_param(h, dom))
            if path.name not in p.sources:
                p.sources.append(path.name)
            for row in t.rows:
                if pos >= len(row) or any(c >= len(row) for c in cols):
                    continue
                key = tuple(row[c] for c in cols)
                if key in p.data and p.data[key] != row[pos]:
                    data.duplicates.append((h, key, p.data[key], row[pos]))
                p.data[key] = row[pos]
        for ix, pos in keys.items():
            set_name = decl.index_set.get(ix, ix)
            for row in t.rows:
                if pos < len(row):
                    _add_set_element(data.sets, set_name, row[pos])


def ad_param(name: str, domain: tuple[str, ...]) -> Param:
    return Param(name, domain)


@lru_cache(maxsize=1)
def load(scenario: str = "cb2026") -> CoalData:
    data = CoalData()
    for key, path in sorted(selected_files(scenario).items()):
        if path.name == "clsteo.txt" or not path.exists():
            continue
        load_file(path, data)
    for extra in ("emmbench.txt", "coalmapping.txt", "input/coalunits.txt"):
        parsed = ad.parse_file(COAL_DIR / extra)
        data.assignments.update(parsed.assignments)
    return data
