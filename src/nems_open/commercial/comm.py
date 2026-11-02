"""SUBROUTINE COMM's yearly chain: the commercial routines in EIA's call order.

COMM calls, every iteration of every year (comm.f line 810):
COMFloorspace, COMServiceDemand, CDistGen, COMTechnologyChoice, COMConsumption,
COMBenchmarking, then CALC111D (111(d) rebates and efficiency costs; it writes
no fuel use, so it is skipped), and COMReport in the final year.

The routines work in place on one dict of Fortran-named arrays, the way the
Fortran works on shared COMMON. The input file readers are only partly ported,
so a run starts from the oracle's state at the top of a year's final iteration
(`start_from_dump`): the module's tables, and its history before that year.
Everything the chain computes for that year is cleared first, so it has to be
rebuilt, not inherited.
"""

import numpy as np

from nems_open import oracle_state
from nems_open.commercial import distgen_tables
from nems_open.commercial.benchmarking import benchmarking, read_kemfac
from nems_open.commercial.consumption import consumption, spray_valve_standard
from nems_open.commercial.distgen import DgState, distgen
from nems_open.commercial.floorspace import FIRST_YEAR, NUM_BLDG, NUM_DIV, Floorspace, FloorspaceInputs
from nems_open.commercial.report import report
from nems_open.commercial.service_demand import service_demand
from nems_open.commercial.technology_choice import Carry, technology_choice
from nems_open.fortran_array import FArray

f32 = np.float32
LAST_YEAR = 61  # 2050
CMFIRSTYR = FIRST_YEAR  # 2019
KSTEOYR = 37  # comvars: benchmark exactly to STEO through 2026
CBECS_IDX = 29  # CBECSyear - (BASEYR - 1)

# Fuel use COMBenchmarking writes into QBLK (and QPRCM into QMORE).
QBLK_NAMES = ("qelcm", "qngcm", "qgfcm", "qgicm", "qdscm", "qrscm", "qrlcm", "qlgcm", "qprcm", "qclcm",
              "qmgcm", "qkscm", "qstcm", "qpvcm", "qbmcm")

# Input tables private to a routine (file readers not yet ported), from the dump after it.
SD_TABLES = ["existimprvht", "existimprvcl", "dcf", "marketpenetrationmels", "melselq",
             "servicesindex", "xplicitmiscshr", "datactrservpenetration", "officepcpenetration",
             "marketpenetrationsc", "pctscsavings", "ct_flag", "applyramp"]
TC_TABLES = ["stretbehav", "costtrendswitch"]
CN_TABLES = ["flooradj", "defaultprices", "ifueltype", "ntek", "steodat", "flagregsteo", "ef1", "ef2", "ef3",
             "nrgbill", "prsvstdsavings", "foodsvchlthldgfloortot", "minfuelalpha", "minfuelbeta"]
BM_TABLES = ["nohist", "decaybm", "lastdecayyr", "steobm2pct"]

# Private arrays a routine writes. Other years come from the dump; the run year is
# cleared (the whole array if it has no year axis). Value: position of the year axis.
SD_PRIVATE = {"ssdnoshell": None, "nsdnoshell": None, "rsdnoshell": None, "totexplicitmiscelq": -1}
TC_PRIVATE = {"sdbyfuel": -1, "purchtechshare": None, "equipsd": -1, "whse_eff": -1, "whse_sd": -1}
CN_PRIVATE = {"unbenchedcon": -1, "cmfinalunbenchuse": -1, "solarpvcontrib": 0}

# CDISTGEN's carried arrays: DgState attribute -> Fortran name, and the year axis.
DG_CARRIED = {"UNITS": ("units", 0), "TRILLS": ("trills", 0), "capacity": ("capacity", 0),
              "TRILLSOWNUSE": ("trillsownuse", 0), "fuelusage": ("fuelusage", 0), "HWBTU": ("hwbtu", 0),
              "SHBTU": ("shbtu", 0), "INVEST": ("invest", 0), "xCumPenSqft": ("xcumpensqft", 0),
              "QCMDGSG": ("qcmdgsg", 0), "com111drensub": ("com111drensub", 0),
              "SolarPVTechPotentialMW": ("solarpvtechpotentialmw", 0),
              "SolarPVAvailRoofArea": ("solarpvavailroofarea", 0), "SolarPVInstalledMW": ("solarpvinstalledmw", 0),
              "SolarPVUsedRoofArea": ("solarpvusedroofarea", 0), "WindTechPotentialMW": ("windtechpotentialmw", 0),
              "WindAvailFS": ("windavailfs", 0), "WindInstalledMW": ("windinstalledmw", 0),
              "WindBldgCount": ("windbldgcount", 0), "xPVGenAdded": ("xpvgenadded", 1),
              "xWindGenAdded": ("xwindgenadded", 1), "CGCOMMGEN": ("cgcommgen", 1), "CGCOMMCAP": ("cgcommcap", 1),
              "CGCOMMQ": ("cgcommq", 1), "CGCPVCOM": ("cgcpvcom", 1), "CGCWNCOM": ("cgcwncom", 1),
              "KCHPCESGEN": ("kchpcesgen", 1), "CFuelCell_MW": ("cfuelcell_mw", 0), "CPV_MW": ("cpv_mw", 0),
              "CMicroTur_MW": ("cmicrotur_mw", 0), "CWind_MW": ("cwind_mw", 0), "CMUSCogen": ("cmuscogen", 1)}
# What other modules supply to CDISTGEN: distgen() name -> Fortran name.
DG_SHARED = {"PELME": "pelme", "PELCM": "pelcm", "PELCMOUT": "pelcmout", "PNGCM": "pngcm", "PDSCM": "pdscm",
             "PCLIN": "pclin", "PCLCM": "pclcm", "EPRPSPR": "eprpspr", "EPRPSTGT": "eprpstgt",
             "SurvFloorTotal": "survfloortotal", "CMNewFloorSpace": "cmnewfloorspace", "COMEUI": "comeui",
             "RPV_MW": "rpv_mw", "UPV_MW": "upv_mw", "RFuelCell_MW": "rfuelcell_mw", "RWind_MW": "rwind_mw",
             "RMicroTur_MW": "rmicrotur_mw"}


def dense(a: FArray) -> np.ndarray:
    """An FArray as a plain array indexed by the Fortran index (index 0 unused);
    indices below 0 are dropped. CDISTGEN's port works on this layout."""
    src = a.a[tuple(slice(max(0, -l), None) for l in a.lb)]
    lb = [max(0, l) for l in a.lb]
    out = np.zeros(tuple(l + n for l, n in zip(lb, src.shape)), dtype=a.a.dtype)
    out[tuple(slice(l, l + n) for l, n in zip(lb, src.shape))] = src
    return out


def undense(d: np.ndarray, like: FArray) -> FArray:
    """Inverse of dense: the part of `d` inside `like`'s Fortran bounds, as an FArray."""
    out = like.copy()
    src = tuple(slice(max(0, l), l + n) for l, n in zip(like.lb, like.a.shape))
    dst = tuple(slice(max(0, -l), None) for l in like.lb)
    out.a[dst] = d[src].astype(like.a.dtype)
    return out


def _clear_year(a: FArray, axis, y: int) -> FArray:
    """A copy with year y zeroed (axis None: the whole array)."""
    a = a.copy()
    if axis is None:
        a.a[...] = 0
        return a
    ax = axis % a.a.ndim
    idx = [slice(None)] * a.a.ndim
    idx[ax] = y - a.lb[ax]
    a.a[tuple(idx)] = 0
    return a


def floorspace(s: dict, y: int, mc_commflsp: np.ndarray, first_call: bool = False) -> None:
    """COMFloorspace, driven by the macro model's floorspace growth (MACOUT/mc_commflsp).
    Rebuilds every year from 2019 to y, so a change to the macro input carries through.
    first_call=True also sets what the first call leaves for the years before: the CBECS-year totals
    and the backcast of new floorspace by construction year (comm.f 1040 to 1068)."""
    fs = Floorspace(FloorspaceInputs.load()).run(mc_commflsp, y)
    if first_call:
        cbecs_idx = FIRST_YEAR - 1
        new = s["cmnewfloorspace"]
        for yy in range(new.lb[2], FIRST_YEAR):
            for r in range(1, NUM_DIV + 1):
                for b in range(1, NUM_BLDG + 1):
                    new[r, b, yy] = fs.new[r, b, fs._new_ix(yy)]
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 2):
                s["cmtotalflspc"][r, b, cbecs_idx] = fs.total[r, b, cbecs_idx]
    for yy in range(FIRST_YEAR, y + 1):
        n = fs._new_ix(yy)
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                s["survfloortotal"][r, b, yy] = fs.surviving[r, b, yy]
                s["agednew"][r, b, yy] = fs.aged_new[r, b, yy]
                s["cmnewfloorspace"][r, b, yy] = fs.new[r, b, n]
                s["cmtotalflspc"][r, b, yy] = fs.total[r, b, yy]
            s["cmtotalflspc"][r, NUM_BLDG + 1, yy] = fs.total[r, NUM_BLDG + 1, yy]
        us_surv = us_new = f32(0.0)
        for b in range(1, NUM_BLDG + 1):
            surv = f32(0.0)
            new = f32(0.0)
            for r in range(1, NUM_DIV + 1):
                surv = f32(surv + s["survfloortotal"][r, b, yy])
                new = f32(new + s["cmnewfloorspace"][r, b, yy])
            us_surv = f32(us_surv + surv)
            us_new = f32(us_new + new)
            s["survfloortotal"][11, b, yy] = surv
            s["cmnewfloorspace"][11, b, yy] = new
            s["cmnewflrspace"][b, yy] = new / f32(1000.0)
            s["cmsurvfloortot"][b, yy] = surv / f32(1000.0)
        s["cmussurvfloortot"][yy] = us_surv / f32(1000.0)
        s["cmusnewfloortot"][yy] = us_new / f32(1000.0)


class Commercial:
    """The commercial module's state between calls: the shared arrays (`s`) plus
    what the Fortran keeps in SAVEd locals (floorspace history, CDISTGEN's arrays,
    technology choice's price-trend counters)."""

    def __init__(self, s: dict, carry: Carry, dg: DgState, dg_templates: dict):
        self.s = s
        self.carry = carry
        self.dg = dg
        self.dg_templates = dg_templates
        self.dg_tables = distgen_tables.read_kgentk()
        self.cogen_el = distgen_tables.read_kcogen()
        self.emission_factor = read_kemfac()

    # ---- set-up ----

    @classmethod
    def start_from_dump(cls, y: int, from_files: bool = False) -> "Commercial":
        """The state at the top of year y's final iteration, from the oracle's dumps
        (y must be a dump year). Arrays the chain writes for year y are cleared.

        from_files=True builds the input tables (SD_TABLES, TC_TABLES, CN_TABLES except the two
        results, BM_TABLES) from EIA's input files instead (first_call.input_tables), so a change
        to a file or a lever reaches the chain. The rest still comes from the dumps."""
        load = lambda tag: oracle_state.load(tag, y)
        s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in load("sd_in").items()}
        sd_out, tc_out, cn_out, bm_out = load("sd_out"), load("tc_out"), load("cn_out"), load("bm_out")
        for k in SD_TABLES:
            s[k] = sd_out[k]
        for k in TC_TABLES:
            s[k] = tc_out[k]
        for k in CN_TABLES:
            s[k] = cn_out[k]
        for k in BM_TABLES:
            s[k] = bm_out[k]
        for src, private in ((sd_out, SD_PRIVATE), (tc_out, TC_PRIVATE), (cn_out, CN_PRIVATE)):
            for k, axis in private.items():
                s[k] = _clear_year(src[k], axis, y)
        if from_files:
            from nems_open.commercial.first_call import input_tables
            from nems_open.snapshot import Snapshot
            files = input_tables(Snapshot()["MACOUT/mc_revser"])
            for k, v in files.items():
                if k == "steodat":       # fuels 1 and 2 come from the macro and supply modules
                    v = v.copy()
                    v.a[:2] = s[k].a[:2]
                if k == "servicesindex":  # years before the first call hold what EIA left there
                    v = v.copy()
                    v.a[:CMFIRSTYR - v.lb[0]] = s[k].a[:CMFIRSTYR - v.lb[0]]
                s[k] = v
        bm_pre = oracle_state.load("bm_pre", y) if oracle_state.available("bm_pre", y) else {}
        if "diffqbm" in bm_pre:
            s["diffqbm"] = bm_pre["diffqbm"]

        pre = load("tc_pre")
        carry = Carry(list(pre["iforward"].a), int(pre["ifwd"]), int(pre["ifmax"]),
                      int(pre["ilaststeoyr"]), int(pre["elasbaseyr"]))

        # CDISTGEN's own arrays are only dumped after the call: keep other years, clear this one.
        # (EIA never clears WindBldgCount, so its dump holds both iterations of the year and
        # a run started here counts one. It is a report; no fuel use depends on it.)
        dg_in, dg_out = load("dg_in"), load("dg_out")
        dg = DgState.empty()
        templates = {}
        for attr, (key, axis) in DG_CARRIED.items():
            arr = dense(dg_out[key])
            idx = [slice(None)] * arr.ndim
            idx[axis] = y
            arr[tuple(idx)] = 0.0
            if attr in ("CGCPVCOM", "CGCWNCOM"):  # these start at 1 until generation is added
                arr[1:10, y] = 1.0
            setattr(dg, attr, arr)
            templates[key] = dg_out[key]
        for attr in ("CFuelCell_MW", "CPV_MW", "CMicroTur_MW", "CWind_MW"):
            getattr(dg, attr)[y - 1] = dense(dg_in[DG_CARRIED[attr][0]])[y - 1]
        xp = dg_out["xpen"]
        prev = np.zeros((12, 12, 12, 6, 11, 7), dtype=f32)
        prev[1:12, 1:12, 1:12, 1:6, 1:11, 1:7] = xp.a[y - 1 - xp.lb[0]]
        dg.xpen = {y - 1: prev}
        for key, t in templates.items():  # CDISTGEN's results as the other routines see them
            s[key] = undense(getattr(dg, next(a for a, (k, _) in DG_CARRIED.items() if k == key)), t)
        return cls(s, carry, dg, templates)

    @classmethod
    def start_from_files(cls, inputs=None) -> "Commercial":
        """COMM before its first call (2019, first iteration), with no oracle dumps: the input
        files, the restart file and zero (initial_state.initial_state)."""
        from nems_open.commercial.initial_state import initial_state
        s = initial_state(inputs)
        carry = Carry([0, 0, 0], 0, int(s["ifmax"]), KSTEOYR + 1989, CBECS_IDX)
        dg = DgState.empty()
        templates = {}
        for attr, (key, _) in DG_CARRIED.items():
            templates[key] = s[key]
            s[key] = undense(getattr(dg, attr), s[key])
        return cls(s, carry, dg, templates)

    # ---- the routines ----

    def floorspace(self, y: int, mc_commflsp: np.ndarray) -> None:
        """COMFloorspace, driven by the macro model's floorspace growth (MACOUT/mc_commflsp).
        Rebuilds every year from 2019 to y, so a change to the macro input carries through."""
        floorspace(self.s, y, mc_commflsp)

    def start_iteration(self, y: int, itr: int) -> None:
        """The top of COMServiceDemand before its calculation: on a year's first iteration,
        last year's shares and efficiencies become the "previous year" values; every
        iteration, solar water heating restarts from zero (comm.f around line 3285)."""
        s = self.s
        if itr == 1 and y == CMFIRSTYR:
            # The previous year is the CBECS base year; Misc. (the last service) starts from base-year shares.
            nfuel = s["prevyrfuelshareofservice"].a.shape[-1]
            base_fs, base_eff = s["fuelshareofservicebase"].a, s["averageefficiencybase"].a
            s["prevyrfuelshareofservice"].a[...] = base_fs[..., :nfuel]
            s["prevyraverageefficiency"].a[...] = base_eff[..., :nfuel]
            s["fuelshareofservice"].a[:, :, -1, :nfuel] = base_fs[:, :, -1, :nfuel]
            s["averageefficiency"].a[:, :, -1, :nfuel] = base_eff[:, :, -1, :nfuel]
            tbm = s["techbymodel"]
            mask = np.zeros(s["prevyrtechshareofservice"].a.shape[3:], dtype=bool)
            for t in range(1, mask.shape[0] + 1):
                for v in range(1, mask.shape[1] + 1):
                    mask[t - 1, v - 1] = tbm[t, v] == 1
            s["prevyrtechshareofservice"].a[..., mask] = s["techshareofservicebase"].a[..., mask]
        if itr == 1 and y > CMFIRSTYR:
            nfuel = s["prevyrfuelshareofservice"].a.shape[-1]
            s["prevyrfuelshareofservice"].a[...] = s["fuelshareofservice"].a[..., :nfuel]
            s["prevyraverageefficiency"].a[...] = s["averageefficiency"].a[..., :nfuel]
            if y == CMFIRSTYR + 1:
                ave, base = s["averageefficiency"].a[..., :nfuel], s["averageefficiencybase"].a
                np.copyto(base, ave, where=ave > 0.0)
            # TechbyModel(t, v) = 1 marks every vintage the model tracks
            tbm = s["techbymodel"]
            mask = np.zeros(s["prevyrtechshareofservice"].a.shape[3:], dtype=bool)
            for t in range(1, mask.shape[0] + 1):
                for v in range(1, mask.shape[1] + 1):
                    mask[t - 1, v - 1] = tbm[t, v] == 1
            tss, prev = s["techshareofservice"].a, s["prevyrtechshareofservice"].a
            prev[..., mask] = tss[..., mask]
        s["solarrenewablecontrib"][1:NUM_DIV, 3, y] = 0.0

    def service_demand(self, y: int) -> None:
        s = self.s
        res = service_demand(s, y)
        for name in ("ServDmdExBldg", "NewServDmd", "ServDmdSurv", "RetireServDmd", "ShellHeatFactor",
                     "ShellCoolFactor", "SSDnoShell", "NSDnoShell", "RSDnoShell", "TotExplicitMiscElQ"):
            s[name.lower()] = getattr(res, name)
        for name, v in res.mel_totals.items():
            s[name.lower()] = v
        s["datctrshare"] = res.DatCtrShare

    def distgen(self, y: int) -> None:
        s = self.s
        shared = {k: dense(s[v]) for k, v in DG_SHARED.items()}
        jp = s["mc_jpgdp"]
        shared["MC_JPGDP"] = {i: jp[i] for i in range(jp.lb[0], jp.lb[0] + jp.a.shape[0])}
        shared["UPIRA_APPYR"] = int(s["upira_appyr"])
        distgen(self.dg_tables, self.dg, shared, self.cogen_el, y)
        for attr, (key, _) in DG_CARRIED.items():
            s[key] = undense(getattr(self.dg, attr), self.dg_templates[key])

    def technology_choice(self, y: int) -> None:
        self.s.update(technology_choice(self.s, self.carry, y))

    def consumption(self, y: int, itr: int = 2) -> None:
        if itr == 1 and y > CMFIRSTYR - 1 and int(self.s["nrgbill"]) > 0:
            self.s.update(spray_valve_standard(self.s, y))
        self.s.update(consumption(self.s, y))

    def benchmarking(self, y: int, itr: int) -> None:
        self.s.update(benchmarking(self.s, y, itr, self.emission_factor))

    def report(self) -> None:
        self.s.update(report(self.s))

    # ---- one call of COMM ----

    def iteration(self, y: int, itr: int, mc_commflsp: np.ndarray) -> None:
        self.floorspace(y, mc_commflsp)
        self.start_iteration(y, itr)
        self.service_demand(y)
        self.distgen(y)
        self.technology_choice(y)
        self.consumption(y, itr)
        self.benchmarking(y, itr)
        if y == LAST_YEAR and itr == 2:
            self.report()

    def qblk(self) -> dict:
        return {k: self.s[k] for k in QBLK_NAMES}
