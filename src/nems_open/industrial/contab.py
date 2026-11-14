"""Consumption tables for the report writer: port of CONTAB and INDFILLCON (ind.f).

After each industry and region, QTYMAIN and QTYRENW are folded into 20 reporting fuels
(CON arrays, indexed fuel, census region 1-4 or 5 for US, year) and added to the
manufacturing or nonmanufacturing heat-and-power table plus the industry's own table.
When INDNUM is 1 (first industry) the tables for that region and year are cleared and
refinery, hydrogen and oil-and-gas cogeneration use is stored.

Works on an oracle-style state dict and updates it in place.
"""

import numpy as np

f32 = np.float32
DIVS = {1: (1, 2), 2: (3, 4), 3: (5, 7), 4: (8, 9), 5: (11, 11)}  # census divisions per region; 5 = US
# qtymain index -> con index (INDFILLCON)
ICON = {1: 1, 2: 19, 3: 2, 4: 2, 5: 16, 6: 2, 7: 3, 8: 4, 9: 5, 10: 6, 11: 7, 12: 8, 13: 17,
        14: 9, 15: 10, 16: 11, 17: 12, 18: 13, 19: 13, 20: 14, 21: 13, 22: 15, 23: 20}
# inddir -> own table
TABLE = {1: "agcon", 2: "agcon", 3: "minecon", 4: "minecon", 5: "minecon", 6: "constcon", 7: "foodcon",
         8: "papercon", 9: "chemcon", 10: "glasscon", 11: "cementcon", 12: "steelcon", 13: "alumcon",
         14: "fabmetalcon", 15: "machinecon", 16: "computecon", 17: "tranequipcon", 18: "elecequipon",
         19: "woodprodcon", 20: "plasticcon", 21: "ltchemcon", 22: "othrnmmcon", 23: "othrprimcon",
         24: "miscfincon"}
ALL_TABLES = ["manhp", "nonhp", "refcon", "h2con"] + sorted(set(TABLE.values()))


def _sum(a) -> np.float32:
    return np.add.reduce(np.asarray(a, dtype=f32), dtype=f32)


def indfillcon(con, row: int, col: int, iy: int, qm, qr, mainfuels: int) -> None:
    """Add QTYMAIN(:,col) and QTYRENW(:,col) into con[:, row-column col, iy]."""
    for i in range(1, mainfuels):
        c = ICON[i]
        con[c, row, iy] = f32(con[c, row, iy]) + f32(qm[i, col])
    for j in range(1, 9):
        con[18, row, iy] = f32(con[18, row, iy]) + f32(qr[j, col])


def indfillcon_ind(qbi, inddir: int, qm, qr, col: int, mainfuels: int) -> None:
    """Same into QtyByInd(:, inddir), a 2-D array."""
    for i in range(1, mainfuels):
        c = ICON[i]
        qbi[c, inddir] = f32(qbi[c, inddir]) + f32(qm[i, col])
    for j in range(1, 9):
        qbi[18, inddir] = f32(qbi[18, inddir]) + f32(qr[j, col])


def contab(s: dict, icr: int) -> None:
    iy = int(s["iyr"]) - 1989
    inddir, indnum = int(s["inddir"]), int(s["indnum"])
    mainfuels = int(s["mainfuels"])
    ncon = 20
    d0, d1 = DIVS[icr]
    qm, qr = s["qtymain"], s["qtyrenw"]

    if indnum == 1:
        s["qtybyind"].a[...] = 0.0
        for name in ALL_TABLES:
            s[name][1:ncon, icr, iy] = 0.0
        ref = s["refcon"]
        ref[1, icr, iy] = _sum(s["qelrf"][d0:d1, iy]) + _sum(s["qeleth"][iy, d0:d1])
        ref[2, icr, iy] = _sum(s["qngrf"][d0:d1, iy]) + _sum(s["qngeth"][iy, d0:d1])
        ref[3, icr, iy] = _sum(s["qclrf"][d0:d1, iy]) + _sum(s["qcleth"][iy, d0:d1])
        ref[6, icr, iy] = _sum(s["qrlrf"][d0:d1, iy])
        ref[7, icr, iy] = _sum(s["qdsrf"][d0:d1, iy])
        ref[8, icr, iy] = _sum(s["qlgrf"][d0:d1, iy])
        ref[10, icr, iy] = _sum(s["qsgrf"][d0:d1, iy])
        ref[11, icr, iy] = _sum(s["qpcrf"][d0:d1, iy]) + _sum(s["qccrf"][d0:d1, iy])
        ref[15, icr, iy] = _sum(s["qotrf"][d0:d1, iy])
        ref[18, icr, iy] = 0.0
        ref[19, icr, iy] = _sum(s["qh2rf"][d0:d1, iy])
        ref[20, icr, iy] = 0.0
        for f in range(1, ncon + 1):
            s["manhp"][f, icr, iy] = ref[f, icr, iy]
        h2 = s["h2con"]
        h2[1, icr, iy] = _sum(s["qelhm"][d0:d1, iy])
        h2[2, icr, iy] = _sum(s["qnghmhp"][d0:d1, iy])
        h2[16, icr, iy] = _sum(s["qnghmpf"][d0:d1, iy])
        og = s["cgogsq"]
        nh = s["nonhp"]
        nh[2, icr, iy] = _sum(og[d0:d1, iy, 3])
        nh[3, icr, iy] = _sum(og[d0:d1, iy, 1])
        nh[6, icr, iy] = _sum(og[d0:d1, iy, 2])

    numind = 24
    if 7 <= inddir <= numind:
        indfillcon(s["manhp"], icr, icr, iy, qm, qr, mainfuels)
    elif inddir < 7:
        indfillcon(s["nonhp"], icr, icr, iy, qm, qr, mainfuels)
    indfillcon(s[TABLE[inddir]], icr, icr, iy, qm, qr, mainfuels)
    if icr == 5:
        indfillcon_ind(s["qtybyind"], inddir, qm, qr, icr, mainfuels)
