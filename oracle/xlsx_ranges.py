"""Flatten an Excel workbook's named ranges into a text file the oracle reads.

Stands in for EIA's ReadRngXLSX, which unzips with WinZip and parses XML in
Fortran. Values go out row by row across each range, as EIA stores them. Numbers
are written at float32 precision because EIA's range buffer is REAL*4. Text cells
are written as "S <text>"; blank cells as 0.

Usage: python -I xlsx_ranges.py <book.xlsx> <sheet> <out.rng>
"""

import re
import sys
import zipfile
import xml.etree.ElementTree as ET

import numpy as np

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def col_num(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def cell_ref(ref: str):
    m = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", ref)
    return col_num(m.group(1)), int(m.group(2))


def sheet_cells(z, sheet_name):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{REL}Relationship")}
    rid = next(s.get(f"{{{NS['r']}}}id") for s in wb.iter(f"{{{NS['m']}}}sheet")
               if s.get("name").lower() == sheet_name.lower())
    target = targets[rid].lstrip("/")
    path = target if target.startswith("xl/") else "xl/" + target

    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{{{NS['m']}}}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))

    cells = {}
    for c in ET.fromstring(z.read(path)).iter(f"{{{NS['m']}}}c"):
        v = c.find("m:v", NS)
        t = c.get("t")
        if t == "inlineStr":
            cells[cell_ref(c.get("r"))] = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
        elif v is None or v.text is None:
            continue
        elif t == "s":
            cells[cell_ref(c.get("r"))] = shared[int(v.text)]
        elif t in ("str", "e"):
            cells[cell_ref(c.get("r"))] = v.text
        elif t == "b":
            cells[cell_ref(c.get("r"))] = float(v.text)
        else:
            cells[cell_ref(c.get("r"))] = float(v.text)
    return wb, cells


def main():
    book, sheet, out = sys.argv[1:4]
    with zipfile.ZipFile(book) as z:
        wb, cells = sheet_cells(z, sheet)
    lines, n = [], 0
    for dn in wb.iter(f"{{{NS['m']}}}definedName"):
        ref = (dn.text or "").strip()
        # EIA's Parse_RangeStr2 reads the first two corners and ignores the rest, so a
        # malformed name like trnldv!$B$3446:$BE$3454:'trnldv'!$BE$3453 (CRCOVID) still loads.
        m = re.match(r"'?([^'!]+)'?!(\$?[A-Z]+\$?\d+)(?::(\$?[A-Z]+\$?\d+))?", ref)
        if not m or m.group(1).lower() != sheet.lower():
            continue
        c1, r1 = cell_ref(m.group(2))
        c2, r2 = cell_ref(m.group(3) or m.group(2))
        vals = []
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                v = cells.get((c, r), 0.0)
                if isinstance(v, str):
                    vals.append("S " + v.replace("\n", " ")[:254])
                else:
                    vals.append(repr(float(np.float32(v))))
        lines.append(f"{dn.get('name').upper()[:16]} {c1} {r1} {c2} {r2} {len(vals)}")
        lines.extend(vals)
        n += 1
    with open(out, "w", encoding="latin-1", errors="replace") as f:
        f.write(f"{n}\n" + "\n".join(lines) + "\n")
    print(f"{n} ranges from sheet {sheet}")


if __name__ == "__main__":
    main()
