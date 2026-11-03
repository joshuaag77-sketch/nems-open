"""Start of a year's CHP (combined heat and power) arrays: port of COGINIT (ind.f).

For one industry and census region, clears this year's CHP generation, capacity,
useful heat and fuel for electricity, adds the planned builds that come online this
year (the plancap.txt records held in COGADD), then adds last year's totals, so each
year's array holds all capacity built so far. The grid share is carried over from
last year. Only runs after the last year of EIA-860 history (MAXCOGYR).

Works on an oracle-style state dict (FArrays keyed by lowercase Fortran name plus
scalars; the COGADD components are the arrays cogadd_year, cogadd_industry, ...) and
updates it in place.
"""

DIVISIONS = {1: (1, 2), 2: (3, 4), 3: (5, 7), 4: (8, 9)}  # census divisions in each region


def coginit(s: dict, inddir: int, indreg: int) -> None:
    curiyr, maxcogyr, numflchp = int(s["curiyr"]), int(s["maxcogyr"]), int(s["numflchp"])
    lo, hi = DIVISIONS[indreg]
    yr = int(s["iyr"]) - 1989
    if curiyr <= maxcogyr:
        return
    coggen, cogcap, cogthr, cogelf, coggrd = (s[k] for k in ("coggen", "cogcap", "cogthr", "cogelf", "coggrd"))
    for arr in (coggen, cogcap, cogthr, cogelf):
        arr[lo:hi, curiyr, inddir, :] = 0.0

    add = {k: s["cogadd_" + k] for k in ("year", "industry", "censusdiv", "fuelind", "gen", "cap", "thr", "elc")}
    for iadd in range(1, int(s["nadds"]) + 1):
        iyear, indi, i = int(add["year"][iadd]), int(add["industry"][iadd]), int(add["censusdiv"][iadd])
        if iyear == yr and indi == inddir and lo <= i <= hi:
            f = int(add["fuelind"][iadd])
            coggen[i, iyear, inddir, f] = coggen[i, iyear, inddir, f] + add["gen"][iadd]  # generation
            cogcap[i, iyear, inddir, f] = cogcap[i, iyear, inddir, f] + add["cap"][iadd]  # capacity
            cogthr[i, iyear, inddir, f] = cogthr[i, iyear, inddir, f] + add["thr"][iadd]  # useful heat
            cogelf[i, iyear, inddir, f] = cogelf[i, iyear, inddir, f] + add["elc"][iadd]  # fuel for electricity only

    for i in range(lo, hi + 1):
        for arr in (coggen, cogcap, cogthr, cogelf):
            arr[i, curiyr, inddir, 1:numflchp] = (arr[i, curiyr - 1, inddir, 1:numflchp]
                                                  + arr[i, curiyr, inddir, 1:numflchp])
        coggrd[i, curiyr, inddir, 1:numflchp] = coggrd[i, curiyr - 1, inddir, 1:numflchp]
