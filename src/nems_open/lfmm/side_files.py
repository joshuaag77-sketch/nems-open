"""The side files LFMM reads besides NEM_TO_LFMM1.gdx, built the way NEMS builds them.

- CoalDRefMap.gdx and crudeshares.gdx: lfprep.gms runs GAMS's GDXXRW on input/CoalD2RefMap.xls (ranges from its
  IndexData sheet) and input/intcrdshr.xls (shipped in input/iem/). GDXXRW is not in the GAMSPy install, so the
  ranges are read through Excel (pywin32) and written with gams.transfer. GDXXRW's layout: rDim=1 cDim=1 is a table
  whose first row holds column labels and first column row labels; rDim=1 alone is label, value pairs; a single cell
  is a scalar. Empty cells and zeros are not written; numeric labels are written without decimals.

    payload = xls_payload(run_folder)     # project Python (pywin32)
    then gams_io.write_gdx per file        # GAMS venv Python
"""

from pathlib import Path

from nems_open.paths import UPSTREAM

# lfprep.gms 1440-1474 and CoalD2RefMap.xls's IndexData sheet: (gdx, xls, [(symbol, sheet, range, rdim, cdim)])
XLS = (
    ("CoalDRefMap.gdx", "coald2refmap.xls", [
        ("CoalDreg2RefRegMap", "CoalDReg2RefReg", "A3:I19", 1, 1),
        ("FirstBldYearMatrix", "bldyrPUmatrix", "C7:L61", 1, 1),
        ("CornTranSupMove", "CornProductionTransfer", "A3:B10", 1, 0),
        ("FirstBldYear", "bldyrPUmatrix", "D3", 0, 0),
    ]),
    ("crudeshares.gdx", "intcrdshr.xls", [
        ("CrudeImportShares", "Sheet1", "A1:CN10", 1, 1),
    ]),
)


def _label(x) -> str:
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x).strip()


def _num(x):
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v != 0 else None


def read_ranges(xls: Path, items) -> dict:
    """{symbol: (dims, rows)} for one workbook, read through Excel."""
    import win32com.client as w
    xl = w.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    out = {}
    try:
        wb = xl.Workbooks.Open(str(Path(xls).resolve()), ReadOnly=True)
        try:
            for sym, sheet, rng, rdim, cdim in items:
                v = wb.Worksheets(sheet).Range(rng).Value
                if rdim == 0 and cdim == 0:
                    out[sym] = ([], [(_num(v) or 0.0,)])
                    continue
                v = [list(r) for r in v]
                rows = []
                if cdim == 1:
                    cols = [_label(c) for c in v[0][1:]]
                    for r in v[1:]:
                        if r[0] is None:
                            continue
                        for c, x in zip(cols, r[1:]):
                            n = _num(x)
                            if n is not None and c:
                                rows.append((_label(r[0]), c, n))
                    out[sym] = (["*", "*"], rows)
                else:
                    for r in v:
                        n = _num(r[1]) if len(r) > 1 else None
                        if r[0] is not None and n is not None:
                            rows.append((_label(r[0]), n))
                    out[sym] = (["*"], rows)
        finally:
            wb.Close(False)
    finally:
        xl.Quit()
    return out


def xls_payloads(run: Path) -> dict[str, dict]:
    """{gdx file name: payload for gams_io.write_gdx}, reading the .xls files from the run folder's input/."""
    out = {}
    for gdx, xls, items in XLS:
        path = Path(run) / "input" / xls
        if not path.exists() and xls == "intcrdshr.xls":
            path = Path(UPSTREAM) / "input" / "iem" / xls
        sym = read_ranges(path, items)
        payload = {"sets": {}, "params": {}, "scalars": {}}
        for name, (dims, rows) in sym.items():
            if not dims:
                payload["scalars"][name] = rows[0][0]
            else:
                payload["params"][name] = (dims, rows, "")
        out[gdx] = payload
    return out
