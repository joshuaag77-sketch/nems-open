"""LDSM hourly system load for one EMM region: DSMHLM, DSMNWS, DSMQSR, uldsm.f.

The year is 864 typical hours (12 months x 3 day types x 24). DSMNWS spreads an
annual load over them with a load shape; DSMHLM adds every end use, the
electrolyzer load and T&D losses, then sorts the hours to find the peak.
"""

import math

import numpy as np

from nems_open.emm.ldsm.common import IND, f32, f64, i, put

MAXSEC = 4
MAXHOUR = 12 * 3 * 24 + 1


def dsmqsr(tosort, index, first, last):
    """EIA's quicksort with insertion sort for short runs, descending, carrying
    INDEX along. Lists, 1-based (element 0 unused), changed in place. Reproduced
    statement by statement: the order of equal loads decides the peak hour."""
    zeroth, second = first - 1, first + 1
    number = last
    jnumb = last - first + 1
    if jnumb <= 2:
        # Quirk kept: two items sort ascending, and the value goes through an
        # INTEGER*2 temporary, so the swapped-in value is truncated.
        if tosort[first] <= tosort[second]:
            return
        itemp = math.trunc(tosort[first])
        tosort[first] = tosort[second]
        tosort[second] = float(itemp)
        index[first], index[second] = index[second], index[first]
        return
    tops, bottom = [0] * 25, [0] * 25
    ipart, limdex = first, 1
    state = 450 if jnumb < 10 else 400
    while True:
        if state == 400:
            state = 100 if number - ipart > 10 else 450
        elif state == 100:
            median = (ipart + number) // 2
            pivot, pivoti = tosort[median], index[median]
            itop, ibot = ipart, number
            if not tosort[ipart] >= pivot:
                tosort[median] = tosort[ipart]
                tosort[ipart] = pivot
                pivot = tosort[median]
                index[median] = index[ipart]
                index[ipart] = pivoti
                pivoti = index[median]
            if not tosort[number] <= pivot:
                tosort[median] = tosort[number]
                tosort[number] = pivot
                pivot = tosort[median]
                index[median] = index[number]
                index[number] = pivoti
                pivoti = index[median]
                if not tosort[ipart] >= pivot:
                    tosort[median] = tosort[ipart]
                    tosort[ipart] = pivot
                    pivot = tosort[median]
                    index[median] = index[ipart]
                    index[ipart] = pivoti
                    pivoti = index[median]
            while True:  # labels 200 and 250
                ibot -= 1
                while tosort[ibot] < pivot:
                    ibot -= 1
                temp2, temp2i = tosort[ibot], index[ibot]
                itop += 1
                while tosort[itop] > pivot:
                    itop += 1
                if itop > ibot:
                    break
                tosort[ibot] = tosort[itop]
                tosort[itop] = temp2
                index[ibot] = index[itop]
                index[itop] = temp2i
            if ibot - ipart >= number - itop:
                tops[limdex], bottom[limdex] = itop, number
                number = ibot
            else:
                tops[limdex], bottom[limdex] = ipart, ibot
                ipart = itop
            limdex += 1
            state = 400
        else:  # 450: insertion sort of ipart..number, then pop the stack (500)
            for k in range(ipart + 1, number + 1):
                pivot, pivoti = tosort[k], index[k]
                itop = k - 1
                if tosort[itop] >= pivot:
                    continue
                while True:
                    tosort[itop + 1] = tosort[itop]
                    index[itop + 1] = index[itop]
                    itop -= 1
                    if itop == zeroth or not tosort[itop] < pivot:
                        break
                tosort[itop + 1] = pivot
                index[itop + 1] = pivoti
            limdex -= 1
            if limdex == 0:
                return
            ipart, number = tops[limdex], bottom[limdex]
            state = 400


def dsmnws(s, numrec, lfpointer, sector):
    """Spread one annual load over the hours with its load shape (numrec 0: the
    region's system shape); add the change to SYLOAD and, in the current year,
    the level to the sector's load."""
    rnb, nhour = i(s, "rnb"), i(s, "nhour")
    if numrec == 0:
        dist = s["distlo_s"][rnb, 1:nhour]
    else:
        dist = s["distlo_eu_s"][numrec, 1:nhour]
    if lfpointer != 0:
        load1 = f64(s["loadforec"][lfpointer, 1])
        load2 = f64(s["loadforec"][lfpointer, 2])
    else:
        load1 = f64(0.0)
        load2 = f64(s["systemload"])
    if math.isnan(load1):
        load1 = f64(0.0)
    syload = s["syload"]  # REAL*8, as is SectorLoad
    if load2 != 0.0:
        syload[1:nhour] = syload[1:nhour] + dist.astype(np.float64) * load2
    if sector != 0 and i(s, "k1") == i(s, "curiyr"):
        s["totsecload"][rnb, sector] = f32(f64(s["totsecload"][rnb, sector]) + load1)
        sl = s["sectorload"]
        sl[1:nhour, sector] = sl[1:nhour, sector] + dist.astype(np.float64) * load1


def dsmhlm(s):
    """Hourly system load for region RNB, year K1: peak, its hour, load factor and
    the peak hours. In the current year also fills SYSLDHR and sector loads."""
    rnb, k1, cur, nhour = i(s, "rnb"), i(s, "k1"), i(s, "curiyr"), i(s, "nhour")
    if k1 == cur:
        s["sectorload"][1:MAXHOUR, 1:MAXSEC] = 0.0
        s["totsecload"][rnb, 1:MAXSEC] = 0.0
        s["sysldhr"][cur, rnb, 1:MAXHOUR] = 0.0
    s["syload"][1:MAXHOUR] = 0.0
    if s["systemload"] > 0.0:
        dsmnws(s, 0, 0, 0)
    k = 0
    systlo = f32(0.0)
    sec_ind = int(s["sec"][IND])
    for n in range(1, i(s, "numsec") + 1):
        for j in range(1, int(s["neuses"][n]) + 1):
            k += 1
            if not (n == sec_ind and j == 4):  # electrolyzer load comes hourly from the hydrogen model
                dsmnws(s, int(s["eurecnum"][k, rnb]), k, n)
        systlo = f32(systlo + s["totsecload"][rnb, n])
    syload = s["syload"]
    h2e, h2m = s["h2_elec_consumed"], s["h2_mwh_consumed"]
    thousand = f32(1000.0)
    for h in range(1, nhour + 1):
        syload[h] = syload[h] + f64(f32(h2e[rnb, h] / thousand))
        if k1 == cur:
            s["sectorload"][h, sec_ind] = s["sectorload"][h, sec_ind] + f64(f32(h2e[rnb, h] / thousand))
            s["totsecload"][rnb, sec_ind] = f32(s["totsecload"][rnb, sec_ind] + f32(h2m[rnb, h] / thousand))
            systlo = f32(systlo + f32(h2m[rnb, h] / thousand))
    td = f32(f32(1.0) + f32(s["nerctdloss"][rnb] * s["ulossadj"][cur]))
    systlo = f32(systlo * td)
    syload[1:nhour] = syload[1:nhour] * f64(td)
    if k1 == cur:
        s["sysldhr"][cur, rnb, 1:nhour] = syload[1:nhour].astype(np.float32)
    # the sort works on a REAL*4 copy
    sorted_load = [0.0] + [float(v) for v in syload[1:nhour].astype(np.float32)]
    hindex = list(range(nhour + 1))
    dsmqsr(sorted_load, hindex, 1, nhour)
    peak = f32(sorted_load[1])
    s["systempeak"][k1] = peak
    s["systempeakhour"][k1] = hindex[1]
    s["totsystemload"][k1] = systlo
    s["systemloadfactor"][k1] = f32(f32(systlo / f32(s["nhouryr"])) / peak)
    npeak, weights, peakhours = i(s, "npeakh"), s["hourlyweights"], s["syspeakhour"]
    j = 0
    for h in range(1, nhour + 1):
        for _ in range(int(weights[hindex[h]])):
            j += 1
            if j > npeak:
                return
            peakhours[j] = hindex[h]
