"""Named ranges of an Excel workbook, the way NEMS reads its spreadsheet inputs.

EIA's ReadRngXLSX unzips the workbook and parses the XML in Fortran; GETRNG* then
copies a range into an array. This does the first part with the standard library.
A range is a flat list of values, row by row; numbers are rounded to float32 as
EIA's REAL*4 range buffer does; text cells come back as str; blank cells as 0.0.
"""

import re
import zipfile
import xml.etree.ElementTree as ET

import numpy as np

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_num(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _cell_ref(ref: str):
    m = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", ref)
    return _col_num(m.group(1)), int(m.group(2))


def _sheet_cells(z, sheet_name):
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
        ref = _cell_ref(c.get("r"))
        if t == "inlineStr":
            cells[ref] = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
        elif v is None or v.text is None:
            continue
        elif t == "s":
            cells[ref] = shared[int(v.text)]
        elif t in ("str", "e"):
            cells[ref] = v.text
        else:
            cells[ref] = float(v.text)
    return wb, cells


def named_ranges(book, sheet: str) -> dict:
    """{NAME: [values]} for every named range on `sheet`. Names are upper case, cut to 16 characters."""
    return {k: v for k, (v, _, _) in named_ranges_shaped(book, sheet).items()}


def named_ranges_shaped(book, sheet: str) -> dict:
    """{NAME: (values, rows, columns)}: named_ranges plus each range's height and width,
    which NEMS's GETRNG* routines use to decide how a range fills an array."""
    out = {}
    with zipfile.ZipFile(book) as z:
        wb, cells = _sheet_cells(z, sheet)
    for dn in wb.iter(f"{{{NS['m']}}}definedName"):
        ref = (dn.text or "").strip()
        # re.match, as the oracle's flattener does: a few definitions trail a third corner
        # (trnldvx.xlsx CRCOVID is "trnldv!$B$3446:$BE$3454:'trnldv'!$BE$3453"); the first two count.
        m = re.match(r"'?([^'!]+)'?!(\$?[A-Z]+\$?\d+)(?::(\$?[A-Z]+\$?\d+))?", ref)
        if not m or m.group(1).lower() != sheet.lower():
            continue
        c1, r1 = _cell_ref(m.group(2))
        c2, r2 = _cell_ref(m.group(3) or m.group(2))
        vals = []
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                v = cells.get((c, r), 0.0)
                vals.append(v.replace("\n", " ")[:254] if isinstance(v, str) else float(np.float32(v)))
        out[dn.get("name").upper()[:16]] = (vals, r2 - r1 + 1, c2 - c1 + 1)
    return out
