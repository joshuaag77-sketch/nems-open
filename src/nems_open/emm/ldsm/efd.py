"""LDSM load duration curves for EFD: DSMEFD and DSMSECWT, uldsm.f.

DSMEFD sorts each EFD segment's hours by (net) load, cuts the sorted curve into
the segment's blocks (block widths in hours from EFDblockx), and hands EFD each
season's block heights and widths (ULHGHT, ULWDTH) and which slice every hour
falls in. DSMSECWT then splits each block's energy by end-use group.
"""

import numpy as np

from nems_open.emm.ldsm.common import f32, f64, i
from nems_open.emm.ldsm.system_load import dsmqsr


def dsmefd(s):
    """EFD load blocks for region RNB: heights, widths, slices, and the hour-to-slice maps."""
    rnb, cur, nhour = i(s, "rnb"), i(s, "curiyr"), i(s, "nhour")
    syload = s["syload"]
    hn_efd = s["hournumberefd"]
    mon, day, hr = s["mon864"], s["dayt864"], s["hr864"]
    weights = s["hourlyweights"]
    nsg = i(s, "efdnumsg")
    fh, lh, dnb = s["efdsgfh"], s["efdsglh"], s["efdsgdnb"]
    blockx, bltyp, width = s["efdblockx"], s["efdsgdbltyp"], s["efdblwidth"]

    sy1 = [0.0] * (nhour + 1)
    sy1_net = [0.0] * (nhour + 1)
    netsw = i(s, "nl_slice_sw")
    caps = [("pv_cap_adj_rest", "wsspvel_cf"), ("pt_cap_adj_rest", "wssptel_cf"), ("so_cap_adj_rest", "wssstel_cf"),
            ("wn_cap_adj_rest", "wsfwiel_cf"), ("wl_cap_adj_rest", "wsfwlel_cf"), ("wf_cap_adj_rest", "wsfwfel_cf")]
    for h in range(1, nhour + 1):
        sy1[h] = float(f32(syload[h]))
        if netsw == 1:
            m, d, hh = int(mon[h]), int(day[h]), int(hr[h])
            v = f64(syload[h])
            for cap, cf in caps:  # REAL*8 capacity x REAL*4 capacity factor
                v = v - f64(s[cap][rnb, cur]) * f64(s[cf][rnb, cur - 1, d, m, hh])
            sy1_net[h] = float(f32(v))
        else:
            sy1_net[h] = sy1[h]
    hourseg = [int(hn_efd[h]) for h in range(nhour + 1)]  # before this year's sort, for DSMSECWT
    order = [0] + [int(hn_efd[h]) for h in range(1, nhour + 1)]
    sy2_net = [0.0] + [sy1_net[order[h]] for h in range(1, nhour + 1)]
    for g in range(1, nsg + 1):
        dsmqsr(sy2_net, order, int(fh[g]), int(lh[g]))
    hn_efd[1:nhour] = np.array(order[1:], dtype=hn_efd.a.dtype)

    maxeftb = s["efdblwidth"].a.shape[0]
    bh = [0.0] * (maxeftb + 1)  # REAL*4 block heights
    pbl = [0] * (maxeftb + 1)
    tmphrsl = np.zeros((13, 4, 25), dtype=np.int32)  # block of each hour (every hour is set)
    abspeak = [0.0] * (nsg + 1)  # REAL*8, by segment
    enover = f32(0.0)
    blk, bls, area = 1, 1, f32(0.0)
    for sgn in range(nsg, 0, -1):
        l = 0
        h1, h2 = int(fh[sgn]), int(lh[sgn])
        abspeak[sgn] = float(f32(sy1[order[h1]]))
        for h in range(h1, h2 + 1):
            o = order[h]
            w1 = int(weights[o])
            tmphrsl[int(mon[o]), int(day[o]), int(hr[o])] = blk
            abspeak[sgn] = max(abspeak[sgn], sy1[o])
            load = f32(sy1[o])
            for _ in range(w1):
                l += 1
                area = f32(area + load)
                if bls != int(dnb[sgn]) and l > blockx[sgn, bls]:
                    dh = f32(f32(l) - blockx[sgn, bls])
                    rest = f32(area - f32(dh * load))
                    if bltyp[sgn, bls] in (b"p", b"P"):
                        bh[blk] = float(f32(abspeak[sgn]))
                        enover = f32(f64(enover) + abspeak[sgn] * f64(width[blk]) - f64(rest))
                        pbl[blk] = 1
                    else:
                        bh[blk] = float(f32(rest / width[blk]))
                    area = f32(dh * load)
                    bls += 1
                    blk += 1
        bh[blk] = float(f32(area / width[blk]))
        blk += 1
        bls = 1
        area = f32(0.0)
    nbl = blk - 1
    s["efdnumbl"] = s["efdnumbl"].dtype.type(nbl)
    if enover != 0.0:
        totarea = f32(0.0)
        for b in range(1, nbl + 1):
            if pbl[b] == 0:
                totarea = f32(totarea + f32(f32(bh[b]) * width[b]))
        if totarea != 0.0:
            ovratio = f32(f32(1) - f32(enover / totarea))
            for b in range(1, nbl + 1):
                if pbl[b] == 0:
                    bh[b] = float(f32(f32(bh[b]) * ovratio))
    bnum = list(range(maxeftb + 1))
    sedef = s["efdsedef"]
    seg, slc = s["efdblseg"], s["efdblslc"]
    for j in range(1, i(s, "efdns") + 1):
        b1, b2 = int(sedef[j, 1]), int(sedef[j, 2])
        if netsw == 0:
            dsmqsr(bh, bnum, b1, b2)
        for k in range(b1, b2 + 1):
            b = k - b1 + 1
            s["ulhght"][b, j, rnb] = bh[k]
            s["ulwdth"][b, j, rnb] = width[bnum[k]]
            s["ulgrp"][b, j, rnb] = seg[bnum[k]]
            s["ulseg"][b, j, rnb] = slc[bnum[k]]
            hit = np.argwhere(tmphrsl[1:13, 1:4, 1:25] == bnum[k]) + 1
            for m, d, hh in hit:
                s["hrtoefdsl"][rnb, m, d, hh] = slc[bnum[k]]
                s["hrtoefdgp"][m, d, hh] = seg[bnum[k]]
        # Quirk kept: the peak is kept by segment but read back by season
        s["ulpeak"][j, rnb] = f32(abspeak[j])
    for k in range(1, nbl + 1):
        s["gblocknumefd"][k, rnb] = bnum[k]
    dsmsecwt(s)


def _group_blocks(s, sy2, rnb):
    """Block energies of one end-use group's sorted hourly load (REAL*8), and
    their total (REAL*4). Same walk as DSMEFD's, without peak blocks."""
    nsg = i(s, "efdnumsg")
    fh, lh, dnb, blockx = s["efdsgfh"], s["efdsglh"], s["efdsgdnb"], s["efdblockx"]
    weights, hn_efd = s["hourlyweights"], s["hournumberefd"]
    energy = {}
    total = f32(0.0)
    blk, bls, area = 1, 1, f32(0.0)
    for sgn in range(nsg, 0, -1):
        l = 0
        for h in range(int(fh[sgn]), int(lh[sgn]) + 1):
            for _ in range(int(weights[int(hn_efd[h])])):
                l += 1
                area = f32(f64(area) + sy2[h])
                if bls != int(dnb[sgn]) and l > blockx[sgn, bls]:
                    dh = f32(f32(l) - blockx[sgn, bls])
                    energy[blk] = f32(f64(area) - f64(dh) * sy2[h])
                    area = f32(f64(dh) * sy2[h])
                    bls += 1
                    total = f32(total + energy[blk])
                    blk += 1
        energy[blk] = area
        total = f32(total + energy[blk])
        blk += 1
        bls = 1
        area = f32(0.0)
    return energy, total


def _assign(s, energy, total, rnb, group):
    if total == 0:
        return
    sedef, gbn = s["efdsedef"], s["gblocknumefd"]
    first = i(s, "curitr") == 1
    for j in range(1, i(s, "efdns") + 1):
        b1, b2 = int(sedef[j, 1]), int(sedef[j, 2])
        for k in range(b1, b2 + 1):
            b = k - b1 + 1
            s["efdblkserv"][b, j, rnb, group] = energy[int(gbn[k, rnb])]
            if first:
                s["efdblkservo"][b, j, rnb, group] = s["efdblkserv"][b, j, rnb, group]


def dsmsecwt(s):
    """Energy in each EFD block by end-use group (efdblkserv) and each group's
    annual load (TOTEULOAD). End uses come grouped; a group's blocks are cut
    when the next group starts, and the last group's after the loop."""
    rnb, nhour = i(s, "rnb"), i(s, "nhour")
    lf, eugrp, eugrpndx = s["loadforec"], s["eugrp"], s["eugrpndx"]
    neuses = s["neuses"]
    h2_ll = int(neuses[1]) + int(neuses[2]) + int(neuses[3])  # the electrolyzer end use
    hs = s["hournumberefd"].a[:nhour].astype(np.int64)  # hour at each sorted position
    s["toteuload"][1:s["toteuload"].a.shape[0], rnb] = 0.0
    sy2 = np.zeros(nhour + 1)  # REAL*8, by sorted position
    last = int(eugrp[1])
    for ll in range(1, i(s, "neu") + 1):
        euload = f32(lf[int(eugrpndx[ll]), 1])
        k = int(eugrp[ll])
        sy3 = np.zeros(nhour + 1, dtype=np.float32)  # load shape by hour
        if ll != h2_ll:
            sy3[1:] = s["distlo_eu_s"][int(s["eurecnum"][int(eugrpndx[ll]), rnb]), 1:nhour]
        else:
            sy3[1:] = (s["h2_elec_consumed"][rnb, 1:nhour] / np.float32(1000.0)).astype(np.float32)
        if k != last:
            energy, total = _group_blocks(s, sy2, rnb)
            _assign(s, energy, total, rnb, last)
            sy2[:] = 0.0
        if ll != h2_ll:
            sy2[1:] = sy2[1:] + (sy3[hs] * euload).astype(np.float64)  # REAL*4 product, REAL*8 sum
        else:
            sy2[1:] = sy2[1:] + sy3[hs].astype(np.float64)
        s["toteuload"][k, rnb] = f32(s["toteuload"][k, rnb] + euload)
        last = k
    energy, total = _group_blocks(s, sy2, rnb)
    _assign(s, energy, total, rnb, last)
