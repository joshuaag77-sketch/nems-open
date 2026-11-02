"""KPARM: COMM's switches (comm.f, first call, lines 636 to 743).

One file of single values and short rows, each separated from the next by a blank line and a
label. The reads follow the Fortran's skips exactly: READ (unit,'(//)') skips n + 1 records.
The switches feed benchmarking (DecayBM, LastDecayYr, ComSTEOBM, NoHist, KSTEOCLS, STEOBM2pct),
service demand (ApplyRamp) and technology choice (STRetBehav, CostTrendSwitch, IFMAX, the cooling
index). The elasticity-run values (ModYear...DSfactor) are read but only used for price studies.
"""

from pathlib import Path

from nems_open.commercial.inputs import CDM, _header, _slashes



def read_kparm(cdm_dir: Path = CDM, num_fuels: int = 8) -> dict:
    """Every KPARM value, keyed by the Fortran name (lower case)."""
    rd = _header(Path(cdm_dir) / "kparm.txt")
    k = {}
    k["dbgr"], k["dbgb"], k["dbgs"], k["dbgy1"], k["dbgy2"] = (int(v) for v in rd.read(5))
    for name in ("reportoption", "coolingtechindexhp", "applyramp", "decaybm", "lastdecayyr"):
        _slashes(rd, 1)
        k[name] = int(rd.read(1)[0])
    _slashes(rd, 7)
    k["sdreportopts1"] = int(rd.read(1)[0])
    _slashes(rd, 1)
    k["sdreportopts2"] = int(rd.read(1)[0])
    for name in ("stretbehav", "costtrendswitch", "comsteobm"):
        _slashes(rd, 1)
        k[name] = int(rd.read(1)[0])
    for name in ("nohist", "ksteocls"):
        _slashes(rd, 2)
        k[name] = int(rd.read(1)[0])
    _slashes(rd, 4)
    k["steobm2pct"] = [int(v) for v in rd.read(num_fuels)]
    _slashes(rd, 1)
    mod_year, end_mod_year, el, ng, ds = rd.read(5)
    k["modyear"], k["endmodyear"] = int(mod_year), int(end_mod_year)
    k["elfactor"], k["ngfactor"], k["dsfactor"] = float(el), float(ng), float(ds)
    _slashes(rd, 1)
    k["ifmax"] = int(rd.read(1)[0])
    return k
