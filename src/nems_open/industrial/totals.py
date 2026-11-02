"""Industry fuel totals for one census region: port of INDTOTAL (ind.f).

Puts together everything an industry burns in one region: process and assembly
fuels (ENPMQTY and the intermediate and renewable arrays), building fuels
(ENBQTY), boiler and CHP fuels (ENSQTY) and byproduct fuels (BYPBSC*), into
QTYMAIN (main fuels), QTYINTR (intermediate) and QTYRENW (renewable). Then nets
the industry's own-use generation out of its electricity, and adds up the
electricity groups that the rest of NEMS uses to split industrial power.

Works on an oracle-style state dict (FArrays keyed by lowercase Fortran name plus
scalars) and updates it in place.

Quirks kept on purpose (see SCOPE.md):
- Intermediate and renewable byproduct fuels (BYPBSCI, BYPBSCR) are added twice:
  once in the fuel-index loop and again in the loops after it.
- EIA's NaN guards only cover some terms; the second BYPBSCI and BYPBSCR loops and
  the steam term from buildings have none, so a NaN there would pass through.
"""

import numpy as np

f32 = np.float32


def _add_unless_nan(arr, idx, value):
    """arr[idx] += value, leaving arr[idx] alone when value is NaN (EIA's guard)."""
    if not np.isnan(value):
        arr[idx] = arr[idx] + value


def indtotal(s: dict, inddir: int, indreg: int, indnum: int) -> None:
    mainfuels, curiyr = int(s["mainfuels"]), int(s["curiyr"])
    qm, qi, qr = s["qtymain"], s["qtyintr"], s["qtyrenw"]
    enpm, enpi, enpr, enb, ens = s["enpmqty"], s["enpiqty"], s["enprqty"], s["enbqty"], s["ensqty"]
    bypi, bypr, bypm = s["bypbsci"], s["bypbscr"], s["bypbscm"]
    xelin, xelinshr = s["xelin"], s["xelinshr"]

    qm[1:mainfuels, indreg] = 0.0
    qi[1:7, indreg] = 0.0
    qr[1:9, indreg] = 0.0
    if indnum == 1:
        xelin[1:4, indreg] = 0.0
        xelinshr[1:4, indreg] = 0.0

    # Process and assembly quantities
    for f in range(1, mainfuels):
        _add_unless_nan(qm, (f, indreg), enpm[f])
    for f in range(1, 7):
        qi[f, indreg] = enpi[f]
    for f in range(1, 9):
        qr[f, indreg] = enpr[f]

    # Buildings
    _add_unless_nan(qm, (1, indreg), enb[5, 1])    # electricity
    _add_unless_nan(qm, (3, indreg), enb[5, 2])    # natural gas
    qi[1, indreg] = qi[1, indreg] + enb[5, 3]      # steam, no NaN guard
    _add_unless_nan(qm, (11, indreg), enb[5, 4])   # distillate
    _add_unless_nan(qm, (12, indreg), enb[5, 5])   # propane

    # Boiler/steam/CHP fuels by universal fuel index, plus byproduct intermediate and renewable fuels
    for f in range(1, 51):
        if f <= mainfuels:
            _add_unless_nan(qm, (f, indreg), ens[f])
        elif f <= 30 or 36 < f <= 40 or f > 48:
            continue
        elif f <= 36:
            _add_unless_nan(qi, (f - 30, indreg), bypi[f - 30])
        else:
            _add_unless_nan(qr, (f - 40, indreg), bypr[f - 40])

    # Byproduct fuels
    for f in range(1, mainfuels):
        _add_unless_nan(qm, (f, indreg), bypm[f])
    for f in range(1, 7):
        qi[f, indreg] = qi[f, indreg] + bypi[f]
    for f in range(1, 9):
        qr[f, indreg] = qr[f, indreg] + bypr[f]

    # Net own-use generation out of electricity (steel and paper take it from PPIS_BSC)
    cfelq, elown, elsale = f32(s["cfelq"]), f32(s["elown"]), f32(s["elsale"])
    electemp = f32(qm[1, indreg] - elown * (cfelq / f32(10.0 ** 6)))
    if inddir not in (8, 12):
        if electemp >= 0:
            qm[1, indreg] = electemp
        else:
            elown = f32(elown + electemp * (f32(10.0 ** 6) / cfelq))
            elsale = f32(elsale - electemp * (f32(10.0 ** 6) / cfelq))
            qm[1, indreg] = 0.0
    else:
        elown, elsale = s["elownx"][inddir, indreg], s["elsalex"][inddir, indreg]
    s["elown"], s["elsale"] = elown, elsale

    for f in range(1, mainfuels):
        qm[mainfuels, indreg] = qm[mainfuels, indreg] + qm[f, indreg]
    for f in range(1, 7):
        qi[7, indreg] = qi[7, indreg] + qi[f, indreg]
    for f in range(1, 9):
        qr[9, indreg] = qr[9, indreg] + qr[f, indreg]

    # Electricity groups: process industries, equipment makers, everything else
    if inddir == 1:
        xelin[1, indreg] = s["refcon"][1, indreg, curiyr]
    if inddir in (7, 8, 9, 12, 13):
        xelin[1, indreg] = xelin[1, indreg] + qm[1, indreg]
    elif 14 <= inddir <= 18:
        xelin[2, indreg] = xelin[2, indreg] + qm[1, indreg]
    else:
        xelin[3, indreg] = xelin[3, indreg] + qm[1, indreg]
    total = xelin[1:3, indreg].sum(dtype=f32)
    xelinshr[1:3, indreg] = xelin[1:3, indreg] / total
