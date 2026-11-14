"""Pieces of the yearly industrial shell (ISEAM) that surround MODCAL.

indbifurc: INDBIFURC (ind.f). Blends the industry's price for each fuel from the covered
(1) and uncovered (2) price, weighted by the share of the industry's emissions under a
carbon price. California (AB 32, region 4 only in model years) uses CARBSHR_AB; other
regions use CARBSHR from indrun.txt. The blended price (slot 3) is also written for all
earlier years of PRCXYR, and for the lagged price PRCXLAG.

roll_lags: the first-iteration block at the top of ISEAM's yearly loop, run before any
industry is processed: each industry and region copies this year's production, UEC,
byproduct intensity, steam, capacity and idle capacity into the "lag" slots that next
year's calculation reads.

electricity_price_slot: ISEAM sets electricity price slot 1 for an industry from a load
type: baseload (24) for primary industries 7, 8, 9, 12, 13; 25 for the metal-based
durables 14 to 18; 26 for the rest.

Work on an oracle-style state dict and update it in place.
"""

import numpy as np

f32 = np.float32
ALLFUELS = 50


def indbifurc(s: dict, ab32: bool = True) -> None:
    ir, inddir, curiyr = int(s["indreg"]), int(s["inddir"]), int(s["curiyr"])
    share = f32(s["carbshr_ab"][inddir, ir]) if ab32 else f32(s["carbshr"][inddir])
    prcx, prcxyr, prcxlag = s["prcx"], s["prcxyr"], s["prcxlag"]
    one = f32(1.0)
    for f in range(1, ALLFUELS + 1):
        prcx[f, ir, 3] = f32(prcx[f, ir, 1]) * share + f32(prcx[f, ir, 2]) * (one - share)
        for k in (1, 2, 3):
            prcxyr[f, ir, curiyr, k] = prcx[f, ir, k]
    for iy in range(9, curiyr):
        for f in range(1, ALLFUELS + 1):
            prcxyr[f, ir, iy, 3] = f32(prcxyr[f, ir, iy, 1]) * share + f32(prcxyr[f, ir, iy, 2]) * (one - share)
    for f in range(1, ALLFUELS + 1):
        prcxlag[f, ir, 3] = f32(prcxlag[f, ir, 1]) * share + f32(prcxlag[f, ir, 2]) * (one - share)


def electricity_price_slot(inddir: int) -> int:
    if inddir in (7, 8, 9, 12, 13):
        return 24
    if 14 <= inddir <= 18:
        return 25
    return 26


def set_electricity_price(s: dict) -> None:
    """prcx(1,indreg,1:2) and prcxyr(1,indreg,curiyr,1:2) from the industry's load-type slot."""
    ir, curiyr = int(s["indreg"]), int(s["curiyr"])
    slot = electricity_price_slot(int(s["inddir"]))
    for k in (1, 2):
        s["prcx"][1, ir, k] = s["prcx"][slot, ir, k]
        s["prcxyr"][1, ir, curiyr, k] = s["prcxyr"][slot, ir, curiyr, k]


def roll_lags(buffers: dict) -> None:
    """buffers[(inddir, indreg)] is that industry-region's saved state (RDBIN/WRBIN fields)."""
    for b in buffers.values():
        b["prodxlag"] = b["prodx"]
        b["prodvxlag"] = b["prodvx"]
        b["enpintlag"].a[...] = b["enpint"].a
        b["bypintlag"].a[...] = b["bypint"].a
        b["stemcurlag"] = b["stemcur"]
        b["prodlag"].a[...] = b["prodcur"].a
        b["idlcaplag"].a[...] = b["idlcap"].a
