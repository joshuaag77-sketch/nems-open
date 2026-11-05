"""National industrial totals: port of NATTOTAL (ind.f).

Run once per industry after region 4. Sums the four regions of QTYMAIN, QTYINTR and
QTYRENW into column 5, totals over fuels, then adds the industry into the running
all-industry arrays TQMAIN, TQINTR and TQRENW (cleared when INDNUM is 1). Lubes and
waxes (main fuel 18) are not summed: the national value is a regression on the
production index of four lube-exposed industries, scaled by 0.70, and then split to
regions with the last SEDS year's shares.

Works on an oracle-style state dict and updates it in place.

Quirks kept on purpose:
- The national fuel sums skip the last slot of each array (mainfuels-1, 6, 8); the
  total slot is filled by the fuel-total loops that follow.
- The lube overwrite sits inside the fuel loop, so every industry resets TQMAIN(18,5)
  to the regression value, and TQMAIN(18,1:4) are recomputed from it each time.
"""

import numpy as np

f32 = np.float32


def nattotal(s: dict, indnum: int) -> None:
    mainfuels, curiyr, msedyr = int(s["mainfuels"]), int(s["curiyr"]), int(s["msedyr"])
    qm, qi, qr = s["qtymain"], s["qtyintr"], s["qtyrenw"]
    tqm, tqi, tqr = s["tqmain"], s["tqintr"], s["tqrenw"]

    qm[1:mainfuels, 5] = 0.0
    qi[1:7, 5] = 0.0
    qr[1:9, 5] = 0.0
    for f in range(1, mainfuels):
        for r in range(1, 5):
            qm[f, 5] = qm[f, 5] + qm[f, r]
    for f in range(1, 7):
        for r in range(1, 5):
            qi[f, 5] = qi[f, 5] + qi[f, r]
    for f in range(1, 9):
        for r in range(1, 5):
            qr[f, 5] = qr[f, 5] + qr[f, r]

    for r in range(1, 6):
        qm[mainfuels, r] = 0.0
        for f in range(1, mainfuels):
            qm[mainfuels, r] = qm[mainfuels, r] + qm[f, r]
    for r in range(1, 6):
        qi[7, r] = qi[1, r] + qi[2, r] + qi[3, r] + qi[4, r] + qi[5, r] + qi[6, r]
    for r in range(1, 6):
        qr[9, r] = 0.0
        for f in range(1, 9):
            qr[9, r] = qr[9, r] + qr[f, r]

    rev = s["mc_revind"]
    for r in range(1, 6):
        for f in range(1, mainfuels + 1):
            if indnum == 1:
                tqm[f, r] = 0.0
            tqm[f, r] = tqm[f, r] + qm[f, r]
            if f == 18 and r == 5:
                num = f32(rev[11, 1, curiyr] + rev[11, 15, curiyr] + rev[11, 33, curiyr] + rev[11, 40, curiyr])
                den = f32(rev[11, 1, 13] + rev[11, 15, 13] + rev[11, 33, 13] + rev[11, 40, 13])
                idx = f32(f32(100.0) * (num / den))
                tqm[f, r] = f32(f32(-5.5183) + f32(4.1380) * f32(np.log(idx))) ** f32(2.0)
                tqm[f, r] = tqm[f, r] * f32(0.70)
        for f in range(1, 8):
            if indnum == 1:
                tqi[f, r] = 0.0
            tqi[f, r] = tqi[f, r] + qi[f, r]
        for f in range(1, 10):
            if indnum == 1:
                tqr[f, r] = 0.0
            tqr[f, r] = tqr[f, r] + qr[f, r]

    q = s["qsluin"]
    tot = q[11, msedyr]
    tqm[18, 1] = tqm[18, 5] * (q[1, msedyr] + q[2, msedyr]) / tot
    tqm[18, 2] = tqm[18, 5] * (q[3, msedyr] + q[4, msedyr]) / tot
    tqm[18, 3] = tqm[18, 5] * (q[5, msedyr] + q[6, msedyr] + q[7, msedyr]) / tot
    tqm[18, 4] = tqm[18, 5] * (q[8, msedyr] + q[9, msedyr]) / tot
