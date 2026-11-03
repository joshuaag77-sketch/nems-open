"""Readers for the AIMMS text data files the CMM reads, and for the declarations in coal.ams.

The coal input files are almost all AIMMS "composite tables": a header row that names the columns,
then one row per record, ending at ";". A column is either an index (a key) or a parameter (a value
defined over the indexes). The model's declarations in coal.ams say which is which, so the parser
needs both. A few files add `NAME := value;` assignments or `NAME := data{'a','b'};` element lists.

Names are case-insensitive in AIMMS; this module lowercases them and drops the "cl::" prefix.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from nems_open.coal.state import COAL_AMS

TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|[^\s,]+')


def _name(token: str) -> str:
    return re.sub(r"^cl::\s*", "", token.strip(), flags=re.I).lower()


def _value(token: str):
    if token[:1] in "\"'" and token[-1:] == token[:1]:
        return token[1:-1]
    # Python's int() accepts "3_4" as 34; plant-unit ids like 3_4 must stay text.
    if re.fullmatch(r"[+-]?\d+", token):
        return int(token)
    if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?", token):
        return float(token.replace("d", "e").replace("D", "e"))
    return token


# --- the model's declarations -------------------------------------------------------------

@dataclass
class Declarations:
    index_set: dict[str, str] = field(default_factory=dict)       # index name -> set name
    sets: set[str] = field(default_factory=set)
    domain: dict[str, tuple[str, ...]] = field(default_factory=dict)   # parameter -> its index names
    kind: dict[str, str] = field(default_factory=dict)            # name -> Set / Parameter / ElementParameter / StringParameter / Variable
    subset_of: dict[str, str] = field(default_factory=dict)      # set -> the set it is a subset of
    lag_identifiers: tuple[str, ...] = ()                         # members of CMMLagData_Identifiers

    def root(self, index_or_set: str) -> str:
        """The outermost set an index or set belongs to (following SubsetOf)."""
        s = self.index_set.get(index_or_set, index_or_set)
        while s in self.subset_of and self.subset_of[s] != s:
            s = self.subset_of[s]
        return s


def _blocks(text: str):
    """Yield (kind, name, body) for each top-level-looking `Kind Name { ... }` declaration."""
    for m in re.finditer(r"^[ \t]*(Set|Parameter|ElementParameter|StringParameter|Variable)[ \t]+(\w+)[ \t]*\{", text, re.M):
        depth, i = 1, m.end()
        while depth and i < len(text):
            c = text[i]
            depth += (c == "{") - (c == "}")
            i += 1
        yield m.group(1), m.group(2), text[m.end(): i - 1]


@lru_cache(maxsize=1)
def declarations() -> Declarations:
    text = COAL_AMS.read_text(encoding="latin-1")
    d = Declarations()
    for kind, name, body in _blocks(text):
        n = name.lower()
        d.kind[n] = kind
        if kind == "Set":
            d.sets.add(n)
            sm = re.search(r"^[ \t]*SubsetOf:\s*(\w+)\s*;", body, re.M)
            if sm:
                d.subset_of[n] = sm.group(1).lower()
            for m in re.finditer(r"^[ \t]*Index:\s*([^;]+);", body, re.M):
                for idx in m.group(1).split(","):
                    d.index_set[idx.strip().lower()] = n
        else:
            m = re.search(r"^[ \t]*IndexDomain:\s*([^;]*?)(?:\|[^;]*)?;", body, re.M | re.S)
            if m:
                dom = m.group(1).strip().strip("()")
                d.domain[n] = tuple(x.strip().lower() for x in dom.split(",") if x.strip())
            else:
                d.domain.setdefault(n, ())
    m = re.search(r"Set\s+CMMLagData_Identifiers\s*\{(.*?)\n\t\t\}", text, re.S)
    if m:
        d.lag_identifiers = tuple(x.lower() for x in re.findall(r"\b\w+\b", re.search(r"Definition:\s*(.*?);", m.group(1), re.S).group(1)) if x.lower() not in ("data",))
    return d


# --- data files --------------------------------------------------------------------------------

@dataclass
class Table:
    headers: list[str]
    rows: list[list]
    line: int = 0                       # line number of the header, for messages

    def column(self, name: str) -> list:
        i = self.headers.index(name.lower())
        return [r[i] if i < len(r) else None for r in self.rows]


@dataclass
class DataFile:
    tables: list[Table] = field(default_factory=list)
    assignments: dict[str, object] = field(default_factory=dict)       # NAME := value;  and NAME := data{...};
    short_rows: int = 0                  # rows with fewer cells than headers


def parse(text: str) -> DataFile:
    out = DataFile()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if re.match(r"COMPOSITE\s+TABLE\s*:", s, re.I):
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("!")):
                j += 1
            headers = [_name(h) for h in re.findall(r"cl::\s*\S+|\S+", lines[j])]
            rows, k = [], j + 1
            while k < len(lines) and lines[k].strip() != ";":
                t = lines[k].strip()
                if t and not t.startswith("!"):
                    cells = [_value(c) for c in TOKEN.findall(t.split("!")[0] if '"' not in t else t)]
                    rows.append(cells)
                    if len(cells) < len(headers):
                        out.short_rows += 1
                k += 1
            out.tables.append(Table(headers, rows, j + 1))
            i = k + 1
            continue
        m = re.match(r"^(?:cl::)?([\w]+)\s*:=\s*(.*)$", s)
        if m and not s.startswith("!"):
            name, rest = m.group(1).lower(), m.group(2)
            while ";" not in rest and i + 1 < len(lines):          # a statement can run over lines
                i += 1
                rest += " " + lines[i].strip()
            body = rest.split(";")[0].strip()
            md = re.match(r"data\s*\{(.*)\}", body, re.S | re.I)
            if md:
                inner = md.group(1)
                quoted = re.findall(r"'[^']*'|\"[^\"]*\"", inner)
                out.assignments[name] = ([x.strip("'\"").strip() for x in quoted] if quoted
                                         else [x.strip() for x in inner.split(",") if x.strip()])
            else:
                out.assignments[name] = _value(body)
        i += 1
    return out


def parse_file(path) -> DataFile:
    from pathlib import Path
    return parse(Path(path).read_text(encoding="latin-1"))
