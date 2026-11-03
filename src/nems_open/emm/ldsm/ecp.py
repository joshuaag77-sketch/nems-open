"""LDSM load duration curves for ECP: DSMECP1 and DSMLCP, uldsm.f.

On the first iteration of each year from UPSTYR on, DSMECP1 rebuilds the load
forecast and hourly load for every year of ECP's horizon and cuts each into ECP's
load blocks (ECPLDCBH heights, ECPLDCBW widths as a fraction of the year).
"""

import numpy as np

from nems_open.emm.ldsm.common import COM, HSTYEAR, IND, RES, TRA, UNCONFA, f32, f64, i, put
from nems_open.emm.ldsm.forecast import dsmdlt, dsmemmv, dsmfor
from nems_open.emm.ldsm.outputs import dsmtor
from nems_open.emm.ldsm.system_load import dsmhlm, dsmqsr

CAPS = [("pv_cap_adj_rest", "wsspvel_cf"), ("pt_cap_adj_rest", "wssptel_cf"), ("so_cap_adj_rest", "wssstel_cf"),
        ("wn_cap_adj_rest", "wsfwiel_cf"), ("wl_cap_adj_rest", "wsfwlel_cf"), ("wf_cap_adj_rest", "wsfwfel_cf")]


def dsmlcp(s, switch=1):
    """ECP load blocks for region RNB, year K1 (switch 1: sort the hours anew)."""
    rnb, k1, cur, nhour = i(s, "rnb"), i(s, "k1"), i(s, "curiyr"), i(s, "nhour")
    syload, hn = s["syload"], s["hournumber"]
    mon, day, hr, weights = s["mon864"], s["dayt864"], s["hr864"], s["hourlyweights"]
    nsg = i(s, "ecpnumsg")
    fh, lh, dnb = s["ecpsgfh"], s["ecpsglh"], s["ecpsgdnb"]
    blockx, bltyp, width = s["ecpblockx"], s["ecpsgdbltyp"], s["ecpblwidth"]
    last_proj = min(i(s, "unyear"), k1)
    netsw = i(s, "nl_slice_sw")

    sy1 = [0.0] * (nhour + 1)
    sy1_net = [0.0] * (nhour + 1)
    for h in range(1, nhour + 1):
        sy1[h] = float(f32(syload[h]))
        if netsw == 1:
            m, d, hh = int(mon[h]), int(day[h]), int(hr[h])
            v = f64(syload[h])
            for cap, cf in CAPS:
                v = v - f64(s[cap][rnb, last_proj]) * f64(s[cf][rnb, cur - 1, d, m, hh])
            sy1_net[h] = float(f32(v))
        else:
            sy1_net[h] = sy1[h]
    order = [0] + [int(hn[h]) for h in range(1, nhour + 1)]
    if switch <= 2:
        sy2_net = [0.0] + [sy1_net[order[h]] for h in range(1, nhour + 1)]
        sy3 = [0.0] + [sy1[order[h]] for h in range(1, nhour + 1)]
        order_rm = list(order)
        if switch == 1:
            for g in range(1, nsg + 1):
                dsmqsr(sy2_net, order, int(fh[g]), int(lh[g]))
                dsmqsr(sy3, order_rm, int(fh[g]), int(lh[g]))
        hn[1:nhour] = np.array(order[1:], dtype=hn.a.dtype)
        wsrc = order
    else:
        wsrc = [0] + [int(s["hournumber3"][h, rnb]) for h in range(1, nhour + 1)]

    bh = s["blockheight"]
    maxectb = bh.a.shape[0]
    pbl = [0] * (maxectb + 1)
    tmphrsl = np.zeros((13, 4, 25), dtype=np.int32)
    enover = f32(0.0)
    blk, bls, area = 1, 1, f32(0.0)
    for sgn in range(nsg, 0, -1):
        l = 0
        h1, h2 = int(fh[sgn]), int(lh[sgn])
        abspeak = f32(sy1[order[h1]])
        for h in range(h1, h2 + 1):
            o = order[h]
            w1 = int(weights[wsrc[h]])
            if k1 == cur:
                tmphrsl[int(mon[o]), int(day[o]), int(hr[o])] = blk
            load = f32(sy1[o])
            abspeak = max(abspeak, load)
            for _ in range(w1):
                l += 1
                area = f32(area + load)
                if bls != int(dnb[sgn]) and l > blockx[sgn, bls]:
                    dh = f32(f32(l) - blockx[sgn, bls])
                    rest = f32(area - f32(dh * load))
                    if bltyp[sgn, bls] in (b"p", b"P"):
                        bh[blk] = abspeak
                        enover = f32(f32(enover + f32(abspeak * width[blk])) - rest)
                        pbl[blk] = 1
                    else:
                        bh[blk] = f32(rest / width[blk])
                    area = f32(dh * load)
                    bls += 1
                    blk += 1
        bh[blk] = f32(area / width[blk])
        blk += 1
        bls = 1
        area = f32(0.0)
    nbl = blk - 1
    put(s, "ecpnumbl", nbl)
    if enover != 0.0:
        totarea = f32(0.0)
        for b in range(1, nbl + 1):
            if pbl[b] == 0:
                totarea = f32(totarea + f32(bh[b] * width[b]))
        if totarea != 0.0:
            ovratio = f32(f32(1) - f32(enover / totarea))
            for b in range(1, nbl + 1):
                if pbl[b] == 0:
                    bh[b] = f32(bh[b] * ovratio)
    if switch != 1:
        return
    bn = s["blocknum"]
    for b in range(1, nbl + 1):
        bn[b] = b
    if netsw == 0:
        heights = [0.0] + [float(bh[b]) for b in range(1, nbl + 1)]
        nums = [0] + [int(bn[b]) for b in range(1, nbl + 1)]
        dsmqsr(heights, nums, 1, nbl)
        bh[1:nbl] = np.array(heights[1:], dtype=np.float32)
        bn[1:nbl] = np.array(nums[1:], dtype=bn.a.dtype)
    sumw = f32(s["sumsegwidth"])
    seg, slc = s["ecpblseg"], s["ecpblslc"]
    for b in range(1, nbl + 1):
        n = int(bn[b])
        s["ecpldcbh"][k1, rnb, b] = bh[b]
        s["ecpldcbw"][k1, rnb, b] = f32(width[n] / sumw)
        s["ecpldcbs"][k1, rnb, b] = seg[n]
        s["ecpldcsl"][k1, rnb, b] = slc[n]
    if k1 == cur:
        for b in range(1, nbl + 1):
            hit = np.argwhere(tmphrsl[1:13, 1:4, 1:25] == int(bn[b])) + 1
            for m, d, hh in hit:
                s["hrtoecpsl"][cur, rnb, m, d, hh] = b
    sedef = s["ecpsedef"]
    for n in range(1, i(s, "ecpns") + 1):
        u = f32(0.0)
        for g in range(int(sedef[n, 1]), int(sedef[n, 2]) + 1):
            load = f32(sy3[int(fh[g])])
            if load > u:
                u = load
        s["uppeak"][n, k1 - cur + 1, rnb] = u
    last_idx = i(s, "ecplastyearindex")
    if cur + 2 <= k1 <= last_idx - 1:
        bn3 = s["blocknum3"]
        if k1 == cur + 2:
            s["hournumber3"][1:hn.a.shape[0], rnb] = hn.a
            for b in range(1, nbl + 1):
                bn3[b, rnb, k1 - cur - 1, 2] = bn[b]
        else:
            for b in range(1, nbl + 1):
                for k in range(1, nbl + 1):
                    if bn[b] == bn3[k, rnb, 1, 2]:
                        break
                else:
                    return  # EIA prints an error and returns
                bn3[k, rnb, k1 - cur - 1, 2] = b


def dsmecp1(s):
    """ECP's view of load: every year of the horizon, rebuilt from the forecast."""
    rnb, cur = i(s, "rnb"), i(s, "curiyr")
    put(s, "ecplastyearindex", cur + i(s, "unfph") - 1)
    nc, unyear, uhbsyr = i(s, "ncensusreg"), i(s, "unyear"), i(s, "uhbsyr")
    for k1 in range(cur, i(s, "ecplastyearindex") + 1):
        put(s, "k1", k1)
        if k1 + uhbsyr <= i(s, "uyr_hist") and k1 + uhbsyr >= HSTYEAR:
            qdem = f32(0.0)
            for q, sector in (("qelrs", RES), ("qelcm", COM), ("qelin", IND), ("qeltr", TRA)):
                a = s["x" + q] if k1 > unyear else s[q]
                qdem = f32(qdem + dsmemmv(s, {k: a[k, k1] for k in range(1, nc + 1)}, rnb, s["sec"][sector]))
            qdem = f32(f32(qdem * UNCONFA) / f32(1000.0))
            put(s, "histshr", f32(s["helasnr"][rnb, k1] / qdem))
        put(s, "ubaseyr", min(k1, unyear))
        dsmfor(s)
        dsmdlt(s)
        dsmhlm(s)
        if k1 == cur:
            dsmtor(s)
        dsmlcp(s, 1)
    put(s, "k1", i(s, "ecplastyearindex") + 1)  # a Fortran DO counter ends one past the last pass
    bn3 = s["blocknum3"]
    for b in range(1, bn3.a.shape[0] + 1):
        for j in range(1, i(s, "unxph") - 3 + 1):
            bn3[b, rnb, j, 1] = bn3[b, rnb, j, 2]
    put(s, "ubaseyr", cur)
