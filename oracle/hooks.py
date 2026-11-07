"""Instrument the oracle's copy of comm.f so it can dump EIA's internal state.

For a routine being ported, the oracle dumps every commercial COMMON array just
before and just after the call ("<tag>_in", "<tag>_out"), plus the routine's
private SAVE arrays at its end. Each dump goes to
run/out/state/<tag>/<year>/<name>.bin with a line in index.txt giving the type,
rank and Fortran bounds, so Python can rebuild arrays with Fortran indexing.
Dumps only happen on the final iteration of the years in DUMP_YEARS.

Output only: nothing here changes a computed value.

Usage: python -I hooks.py <upstream> <source.f90 to instrument in place> [module]
module is comm (default), resd or emm (src is then util.f90; the other EMM
files must already be patched into the build folder).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Build and run folders live under WORK: this folder by default; NEMS_ORACLE_WORK moves them (build_wsl.sh keeps
# Linux objects and run folders on the Linux file system, away from the Windows ones).
WORK = Path(os.environ.get("NEMS_ORACLE_WORK", HERE))
BUILD = WORK / "build"
RUN = WORK / "run"

# 2019, 2020, 2021, 2025, 2026, 2027, 2030, 2040, 2050
DUMP_YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]
if os.environ.get("NEMS_ORACLE_YEARS"):       # e.g. "30": a small run for one new dump point
    DUMP_YEARS = [int(y) for y in os.environ["NEMS_ORACLE_YEARS"].split(",")]
FIRST_YEAR = 30  # CMFirstYr: first-call dumps are written under this year

# Routine being ported: (tag, the CALL line in COMM, label line at the routine's
# end where private arrays are dumped, private arrays to dump there, and saved
# values carried between iterations). Carried values are also dumped at the end
# of the non-final iteration ("<tag>_pre"), which is their value when the final
# iteration starts.
TARGETS = [
    ("sd", r"CALL COMServiceDemand\s*\(RCDBG\)", r"^490\s+CONTINUE", [
        "ExistImprvHt", "ExistImprvCl", "dcf", "MarketPenetrationMels", "MelsElQ",
        "ServicesIndex", "xplicitmiscshr", "DataCtrServPenetration", "OfficePCPenetration",
        "MarketPenetrationSC", "pctSCSavings", "CT_flag", "DatCtrShare", "ApplyRamp",
        "SSDnoShell", "RSDnoShell", "NSDnoShell", "TotExplicitMiscElQ",
        "XfmrsDry", "KitchenVent", "Security", "LabRefFrz", "MedImaging", "LrgVidBoard",
        "CoffeeBrewers", "ElVehicles", "FumeHoods", "Laundry", "Elevators", "Escalators",
        "ITEquip", "OfficeUPS", "Shredder", "OfficePBE", "VoiceIP", "POSsystems",
        "WarehouseRobots", "Televisions",
    ], []),
    ("tc", r"CALL COMTechnologyChoice\s*\(RCDBG\)", r"^\s*9100\s+CONTINUE", [
        "SDbyFuel", "SSDnoShell", "RSDnoShell", "NSDnoShell", "WHSE_EFF", "WHSE_SD",
        "PurchTechShare", "EquipSD", "STRetBehav", "CostTrendSwitch",
    ], ["iforward", "ifwd", "IFMAX", "iLastSTEOyr", "elasbaseyr"]),
    ("cn", r"CALL COMConsumption\s*\(RCDBG\)", r"^\s*210 CONTINUE\s+! across Building Types", [
        "UnBenchedCon", "CMFinalUnbenchUse", "SolarPVContrib", "Trills", "TrillsOwnUse", "TrillsOwnUseAdj",
        "shbtu", "hwbtu", "fuelusage", "FloorAdj", "defaultprices", "ifueltype", "ntek",
        "STEOdat", "FlagRegSTEO", "EF1", "EF2", "EF3", "NRGBILL", "STIMULUS",
        "prsvStdSavings", "prsvShpSavings", "FoodSvcHlthLdgFloorTot", "FoodSvcHlthLdgFlrPrev",
    ], []),
]

# Added for the rest of the commercial module. A target may carry a sixth item:
# "before" puts the private-array dump ahead of the end marker (for a RETURN).
TARGETS += [
    ("dg", r"CALL CDistGen\s*\(curiyr,curitr,rcrpt,rcdbg\)", r"before:^\s*RETURN\s+! SEND CONTROL BACK TO COMM", [
        "UNITS", "TRILLS", "capacity", "TRILLSOWNUSE", "fuelusage", "HWBTU", "SHBTU", "INVEST", "Ifueltype",
        "QCMDGSG", "QRSDGSG", "PRSDGSG", "xCumPenSqft", "com111drensub", "CMCogenEL",
        "SolarPVTechPotentialMW", "SolarPVAvailRoofArea", "SolarPVInstalledMW", "SolarPVUsedRoofArea",
        "WindTechPotentialMW", "WindAvailFS", "WindInstalledMW", "WindBldgCount",
        "xPVGenAdded", "xWindGenAdded", "XINXDECAY", "xRPS", "iNumYrsatRPSBaseRate", "iNumRPSCreditYrs", "xpen",
    ], []),
    ("bm", r"CALL COMBenchmarking\s*\(RCDBG,RCQUAN\)", r"^510\s+FORMAT \(A20,1X,A20", [
        "WaterServicesElQ", "TelecomServicesElQ", "DiffQBM", "SolarPVContrib", "ApplyRamp",
        "LastDecayYr", "DecayBM", "NoHist", "STEOBM2pct", "EF1", "EF2", "EF3", "NRGBILL", "STIMULUS", "STEOBM",
        "EmissionFactor", "CMEmissions",
    ], ["DiffQBM"]),
    # COMReport runs only in the last year; the call is the tail of a one-line IF.
    ("rp", r"IF\s*\(CURIYR\.EQ\.LASTYR\s*\.AND\.\s*FCRL\.EQ\.1\)\s*&\s*\n\s*CALL COMReport\s*\(RCDBG,RCRPT,SDReportOpts,ReportOption\)",
     r"before:^\s*RETURN\s*\n\s*END\s*\n!\*+\s*\n! Floorspace Survival function", [
         "CMFinalUnbenchUse", "UnBenchedCon",
     ], []),
]

# Run once, in the first iteration of the first year: state around the first call
# of a routine (the file readers and one-time edits live there).
FIRST_CALL = ["tc", "sd"]

# Dump points inside a routine with no call to wrap: (tag, line to follow, private arrays).
# The dump is the first-call state, so it only fires in the first iteration of the first year.
PROBES = [
    ("frd", r"^\s*! End of block to read input data", [
        "ExistImprvHt", "ExistImprvCl", "dcf", "MarketPenetrationMels", "MelsElQ",
        "ServicesIndex", "xplicitmiscshr", "DataCtrServPenetration", "OfficePCPenetration",
        "MarketPenetrationSC", "pctSCSavings", "CT_flag", "ApplyRamp", "BASELINEBKWHCM",
    ]),
    # CDistGen's tables, right after it reads KCOGEN and KGENTK.
    ("fdg", r"^\s*xpctWindSuitable=\.10", [
        "CMCogenEL", "NUMTECHS", "NUMYEARS", "NUMDIV", "NUMBLDG", "NVINT", "iGenCapCostYr", "XOPERHOURS",
        "GlobalLearn", "xpctPVSuitable", "XBeta", "Xc0", "XINX", "XINXFY", "XINXLY", "XTAXRATE", "XDOWNPAYPCT",
        "XINTRATE", "XTERM", "XINFLATION", "XALPHA", "XPENPARM", "xkwMin", "xkwmax", "xScaleFac", "ISKIP",
        "iRPSStartYear", "iRPSPhaseOutYear", "iRPSGrandFatherYear", "AEQUIPNAME", "IFUELTYPE", "IFIRSTYR",
        "ILASTYR", "XKW", "XELEFF", "XLOSSFAC", "XDEGRAD", "XEQLIFE", "xtxlife", "xdep", "XWHRECOVERY",
        "XINSTCOST", "XCAPCOST", "XMAINTCST", "xIntervalCst", "iIntervalYrs", "XAVAIL", "XTXCRPCT",
        "xTXCrMaxPerKW", "xTXCrMaxPerSys", "comtxcrpct_div", "xRPS", "iNumYrsatRPSBaseRate", "iNumRPSCreditYrs",
        "NumPVNiche", "xSolarInsolation", "xSqftShare", "xRateScalar", "xRoofAreatoSqftRatio", "xWindSpeed",
        "xNGRateScalar", "XBLDGSHARE", "cbecsFlspcCatShare", "cbecsAVGSQFT", "xelecavgkwh", "XEXOGPEN",
        "XA", "XB", "XC", "xpctWindSuitable",
    ]),
]

# Shared state dumped around each target call.
STATE_INCLUDES = ["parametr", "ncntrl", "apq", "macout", "eusprc", "mxpblk", "emmparm", "emission", "qsblk",
                  "cogen", "bldglrn", "uefpout", "uecpout", "tranrep", "comparm", "comvars", "commrep"]
STATE_BLOCK_FILES = ["comparm", "comvars", "commrep"]
# Arrays from other modules' blocks that the commercial routines read.
STATE_EXTRA = ["QELCM",                                   # service demand
               "PELCM", "PNGCM", "PDSCM", "XPELCM", "XPNGCM", "XPDSCM",
               "PELCMOUT", "MC_JPGDP", "MC_RMGBLUSREAL",  # technology choice
               "PRSCM", "PLGCM", "PCLCM", "PMGCM", "PKSCM",  # consumption (minor fuels)
               "MC_NP", "PCLIN", "TRQ_ELEC", "WHRFOSS", "QSBMCM", "EMCM", "EMCMC",  # benchmarking
               "QNGCM", "QGFCM", "QGICM", "QDSCM", "QRSCM", "QRLCM", "QLGCM", "QPRCM", "QCLCM",
               "QMGCM", "QKSCM", "QSTCM", "QPVCM", "QBMCM",
               # distributed generation
               "CGCOMMGEN", "CGCOMMCAP", "CGCOMMQ", "CGCPVCOM", "CGCWNCOM", "KCHPCESGEN",
               "CFuelCell_MW", "CPV_MW", "RPV_MW", "UPV_MW", "RFuelCell_MW", "CWind_MW", "RWind_MW",
               "CMicroTur_MW", "RMicroTur_MW", "PELME", "EPRPSPR", "EPRPSTGT", "UPIRA_APPYR"]
DECL_FILES = ["parametr", "comparm", "comvars", "commrep", "qblk", "apq", "ampblk",
              "mpblk", "mxpblk", "eusprc", "macout", "emmparm", "emission", "qsblk", "cogen", "tranrep",
              "bldglrn", "uefpout", "uecpout"]

# Residential: every routine is CONTAINed in SUBROUTINE RESD and shares MODULE R_,
# so the state dump USEs R_ instead of including blocks. Targets are dicts:
# call (regex for the CALL line in RESD), nth (which match, 0-based; RESD calls
# some routines twice, once for the base year and once after), end (regex for the
# routine's last line), before (dump before that line rather than after it),
# private, carried.
RESD_DUMP_YEARS = [31, 32, 33, 36, 37, 38, 41, 51, 61]  # 2020 2021 2022 2025 2026 2027 2030 2040 2050
# ORACLE_DUMP_YEARS="31,32,36" narrows the dumps (a full residential set is 18 GB); NEMS_ORACLE_YEARS does the
# same for every module and is what build_wsl.sh passes through.
for _var in ("ORACLE_DUMP_YEARS", "NEMS_ORACLE_YEARS"):
    if os.environ.get(_var):
        RESD_DUMP_YEARS = [int(y) for y in os.environ[_var].split(",")]
RESD_TARGETS = [
    dict(tag="pr", call=r"IF \(CurCalYr\.GE\.RECSYear\) CALL RDPR\b"),
    dict(tag="nh", call=r"CALL NEWHSE\b"),
    dict(tag="sq", call=r"CALL SQFTCALC\b"),
    # RECS base year only (2020)
    dict(tag="ex", call=r"CALL EXCONS\b"),
    dict(tag="bb", call=r"CALL RSBENCH\b", nth=0),
    dict(tag="nb", call=r"CALL NEMSCN\b", nth=0),
    dict(tag="rb", call=r"CALL RESDRP\b", nth=0),
    # Every year after
    dict(tag="hv", call=r"CALL RSHVAC\b"),
    # end uses: ht heating, cl cooling, cw clothes washing, dw dishwashing, wh water
    # heating, ck cooking, dy drying, rf refrigeration, fz freezing;
    # t = technology choice, a = equipment added/replaced, c = consumption
    dict(tag="htt", call=r"CALL RHTRTEC\b", end=r"^END SUBROUTINE RHTRTEC", before=True, carried=["HEATSYS"]),
    dict(tag="hta", call=r"CALL RHTRADD\b"),
    dict(tag="dg", call=r"CALL RDISTGEN\b", nth=1, end=r"^RETURN  !SEND CONTROL BACK TO RESD", before=True,
         carried=["Income_L", "Households_L", "ElecRate_L", "PopDensity_L", "Lag1Installs", "Lag2Installs",
                  "ProjectedInstalls", "CumUnits", "CumUnits_L"]),
    dict(tag="clt", call=r"CALL RCLTEC\b"),
    dict(tag="cla", call=r"CALL RCLADD\b", end=r"^END SUBROUTINE RCLADD", before=True, carried=["EQCPN90"]),
    dict(tag="cwt", call=r"CALL RCWTEC\b"),
    dict(tag="cwa", call=r"CALL RCWADD\b"),
    dict(tag="dwt", call=r"CALL RDWTEC\b"),
    dict(tag="dwa", call=r"CALL RDWADD\b"),
    dict(tag="wht", call=r"CALL RWHTEC\b"),
    dict(tag="wha", call=r"CALL REUADD\b", nth=0),  # EU = 5
    dict(tag="ckt", call=r"CALL RSTVTEC\b"),
    dict(tag="cka", call=r"CALL REUADD\b", nth=1),  # EU = 6
    dict(tag="dyt", call=r"CALL RDRYTEC\b"),
    dict(tag="dya", call=r"CALL RDRYADD\b"),
    dict(tag="rft", call=r"CALL RREFTEC\b"),
    dict(tag="rfa", call=r"CALL RREFADD\b"),
    dict(tag="fzt", call=r"CALL RFRZTEC\b"),
    dict(tag="fza", call=r"CALL RFRZADD\b"),
    dict(tag="htc", call=r"CALL RHTRCON\b", end=r"^END SUBROUTINE RHTRCON", before=True,
         carried=["EFANUEC", "NFANUEC"]),
    dict(tag="clc", call=r"CALL RCLCON\b"),
    dict(tag="cwc", call=r"CALL RCWCON\b"),
    dict(tag="dwc", call=r"CALL RDWCON\b"),
    dict(tag="whc", call=r"CALL RWHCON\b"),
    dict(tag="ckc", call=r"CALL RSTOVCON\b"),
    dict(tag="dyc", call=r"CALL RDRYCON\b"),
    dict(tag="rfc", call=r"CALL RREFCON\b"),
    dict(tag="fzc", call=r"CALL RFRZCON\b"),
    dict(tag="lt", call=r"CALL LTCNS\b", end=r"^END SUBROUTINE LTCNS", before=True,
         carried=["LTREPFUTly", "LTrepstkly", "LTrepconsly"]),
    dict(tag="ap", call=r"CALL APCNS\b"),
    dict(tag="sh", call=r"CALL SHTCNS\b"),
    dict(tag="sa", call=r"CALL APPCNS\b"),
    dict(tag="fu", call=r"CALL FUELCN\b"),
    dict(tag="be", call=r"CALL RSBENCH\b", nth=1),
    dict(tag="ne", call=r"CALL NEMSCN\b", nth=1),
    dict(tag="re", call=r"CALL RESDRP\b", nth=1),
    # Final year only (2050, dump year 61): reports
    dict(tag="nt", call=r"CALL NHTSHR\b"),
    dict(tag="r2", call=r"CALL RESDRP2\b"),
    # Start of each projection year (after RDPR): everything the yearly chain reads,
    # for the end-to-end test that runs every port in RESD's order.
    dict(tag="yb", call=r"CALL NEWHSE\b", routines=[
        "NEWHSE", "SQFTCALC", "RSHVAC", "RHTRTEC", "RHTRADD", "RDISTGEN", "RCLTEC", "RCLADD", "RCWTEC",
        "RCWADD", "RDWTEC", "RDWADD", "RWHTEC", "REUADD", "RSTVTEC", "RDRYTEC", "RDRYADD", "RREFTEC",
        "RREFADD", "RFRZTEC", "RFRZADD", "RHTRCON", "RCLCON", "RCWCON", "RDWCON", "RWHCON", "RSTOVCON",
        "RDRYCON", "RREFCON", "RFRZCON", "LTCNS", "APCNS", "SHTCNS", "APPCNS", "FUELCN", "RSBENCH",
        "NEMSCN", "RESDRP", "NHTSHR", "RESDRP2"]),
]
RESD_STATE_BLOCK_FILES = ["resdrep", "rtek", "rscon", "rseff"]
RESD_STATE_EXTRA = ["QELRS", "QNGRS", "QDSRS", "QLGRS", "QKSRS", "QBMRS", "QGERS", "QSTRS", "QPVRS",
                    "QTRRS", "PELRSOUT", "PELRS", "PNGRS", "PDSRS", "PLGRS", "PKSRS", "MC_JPGDP"]
# Other modules' blocks the residential routines can read. Around a target, any of
# their arrays the routine mentions is dumped too (not in 'final').
RESD_WIDE_FILES = ["ncntrl", "qblk", "mpblk", "ampblk", "macout", "eusprc", "qsblk", "cogen", "uefpout",
                   "uecpout", "e111d", "steoblock", "emission", "emablk", "bldglrn"]
RESD_DECL_FILES = ["parametr", "resdrep", "rtek", "rscon", "rseff", "apq"] + RESD_WIDE_FILES

# Electricity (EMM): UTIL is the yearly entry. Targets are dicts as for resd.
# Each gets its own dump routine, built from the includes of the target routine
# and everything it calls (EMM has 121 includes; they do not all compile in one
# routine). The ECP and EFD solves run in AIMMS, which we do not have: EMM_SWAPS
# rewrite those calls in the oracle's copy of util.f.
EMM_DUMP_YEARS = [31, 32, 33, 36, 37, 38, 41, 51, 61]  # 2020 2021 2022 2025 2026 2027 2030 2040 2050
EMM_TARGETS = [
    # home: the files whose routines count when collecting what a target uses. The
    # call tree reaches most of EMM through shared helpers; following it everywhere
    # made each dump 350 MB, mostly EFD dispatch and storage arrays EFP never reads.
    dict(tag="ld", call=r"CALL ELLDSM\(IDSM\)", routines=["ELLDSM"],   # LDSM: load curves for ECP, EFD, EFP
         home=["uldsm"], ryears_only=True),  # 2021, 2030, 2050 only (disk)
    dict(tag="fp", call=r"CALL ELEFP\b", routines=["ELEFP"],           # EFP: prices (first pass; the second
         home=["uefp", "udaf"], ryears_only=True),                                      # runs only with STEO price benchmarking)
]
# LDSM routines, around their calls in uldsm.f (ELLDSM's region loop, then DSMECP1's
# ECP-horizon loop). Region targets dump as "<name>_rNN" for the regions in
# EMM_DUMP_REGIONS (all 25 would be 5x the disk for little more coverage). itr=1:
# the routine only runs on a year's first iteration, so dump there instead of the
# final one. cond: an extra Fortran test for the dump.
EMM_DUMP_REGIONS = [1, 13]
EMM_REGION_YEARS = [32, 41, 61]  # 2021 2030 2050: region dumps filled the disk at 5 regions x 9 years
EMM_TARGETS += [
    dict(tag="ca", call=r"CALL DSMCADJ\b", file="uldsm", home=["uldsm"], routines=["DSMCADJ"]),
    dict(tag="fo", call=r"CALL DSMFOR\(WHOOPS\)", file="uldsm", home=["uldsm"], routines=["DSMFOR"], region=True),
    dict(tag="dl", call=r"CALL DSMDLT\b", file="uldsm", home=["uldsm"], routines=["DSMDLT"], region=True),
    dict(tag="hl", call=r"CALL DSMHLM\b", file="uldsm", home=["uldsm"], routines=["DSMHLM"], region=True),
    dict(tag="ep", call=r"CALL DSMEFP\b", file="uldsm", home=["uldsm"], routines=["DSMEFP"], region=True),
    dict(tag="to", call=r"CALL DSMTOR\b", file="uldsm", home=["uldsm"], routines=["DSMTOR"], region=True),
    dict(tag="ef", call=r"CALL DSMEFD\b", file="uldsm", home=["uldsm"], routines=["DSMEFD"], region=True),
    dict(tag="e1", call=r"CALL DSMECP1\(WHOOPS\)", file="uldsm", home=["uldsm"], routines=["DSMECP1"], region=True,
         itr=1),
    dict(tag="lc", call=r"CALL DSMLCP\(1\)", file="uldsm", home=["uldsm"], routines=["DSMLCP"], region=True, itr=1,
         cond="K1 .EQ. CURIYR"),
]
# EFP routines, per EMM region, around their calls in uefp.f. region="NRGN": the
# region is the routine's argument, not a COMMON variable, so the call passes it.
# AVRPRC's first half (CWIP, plant in service, depreciation, taxes) runs only on
# a year's first iteration, so each AVRPRC call has a first-iteration target (*1)
# and a final-iteration one. Each region's books (EFP's direct-access files) are
# loaded into COMMON by ELGLTR before these calls, so they are in the dumps.
_EFP = dict(file="uefp", home=["uefp", "udaf"], region="NRGN")
# GL and AVRPRC reach most of EFP, so their dumps are about 50 MB a region: keep
# them to region 1 in 2030 (few=True). The routine-level dumps below stay full.
_EFP_FEW = dict(_EFP, few=True)
EMM_TARGETS += [
    dict(tag="gg", call=r"CALL GL\(NRGN,ICALL\)", nth=0, routines=["GL"], **_EFP_FEW),
    dict(tag="gt", call=r"CALL GL\(NRGN,ICALL\)", nth=1, routines=["GL"], **_EFP_FEW),
    dict(tag="gd", call=r"CALL GL\(NRGN,ICALL\)", nth=2, routines=["GL"], **_EFP_FEW),
    dict(tag="ag", call=r"CALL AVRPRC\(NRGN,ICALL\)", nth=0, routines=["AVRPRC"], **_EFP_FEW),
    dict(tag="ag1", call=r"CALL AVRPRC\(NRGN,ICALL\)", nth=0, routines=["AVRPRC"], itr=1, **_EFP_FEW),
    dict(tag="at", call=r"CALL AVRPRC\(NRGN,ICALL\)", nth=1, routines=["AVRPRC"], **_EFP_FEW),
    dict(tag="at1", call=r"CALL AVRPRC\(NRGN,ICALL\)", nth=1, routines=["AVRPRC"], itr=1, **_EFP_FEW),
    dict(tag="ad", call=r"CALL AVRPRC\(NRGN,ICALL\)", nth=2, routines=["AVRPRC"], **_EFP_FEW),
    dict(tag="ad1", call=r"CALL AVRPRC\(NRGN,ICALL\)", nth=2, routines=["AVRPRC"], itr=1, **_EFP_FEW),
]
# Inside AVRPRC, routine by routine, for the generation component only (site_cond
# is tested where the call is, since ICALL is local). Transmission and
# distribution are covered by the whole-AVRPRC dumps above.
_G = dict(site_cond="ICALL .EQ. 'G'", **_EFP)
EMM_TARGETS += [dict(tag=tag, call=call, routines=[name], itr=itr, **_G) for tag, name, call, itr in [
    ("x_adcr", "ELADCR", r"CALL ELADCR\b", 1),
    ("x_cwip", "ELCWIP", r"CALL ELCWIP\(NRGN,ICALL\)", 1),
    ("x_nd", "ELND", r"CALL ELND\(NRGN,6,ICALL\)", 1),
    ("x_phin", "ELPHIN", r"CALL ELPHIN\(NRGN\)", 1),
    ("x_sl", "ELSL", r"CALL ELSL\(NRGN\)", 1),
    ("x_itc", "ELITC", r"CALL ELITC\b", 1),
    ("x_bkdp", "ELBKDP", r"CALL ELBKDP\(NRGN,ICALL\)", 1),
    ("x_txdp", "ELTXDP", r"CALL ELTXDP\(NRGN,ICALL\)", 1),
    ("x_tsaf", "ELTSAF", r"CALL ELTSAF\b", 1),
    ("x_xpns", "ELXPNS", r"CALL ELXPNS\(NRGN,ICALL\)", None),
    ("x_inex", "ELINEX", r"CALL ELINEX\(NRGN\)", None),
    ("x_revs", "ELREVS", r"CALL ELREVS\(ICALL,NRGN\)", None),
    ("x_rate", "ELRATE", r"CALL ELRATE\(ICALL,NRGN\)", None),
    ("x_stmt", "STMTS", r"IF \(EFPFCRL \.EQ\. 1\) CALL STMTS\(NRGN,ICALL\)", None),
]]
for _t in EMM_TARGETS:
    if _t["tag"] == "x_rate":  # ELRATE reaches most of EFP too: about 50 MB a region
        _t["few"] = True
# ELGLTR's cost routines, after it has loaded the region's books (generation;
# CAPCOST once per ownership type), and COMPPRC, which GENERA runs when USW_POL=4
# (it is in cb2026). Calls on a continuation line are matched as the whole IF.
EMM_TARGETS += [
    dict(tag="y_cap1", call=r"CALL CAPCOST\(NRGN,ICALL,N\)", routines=["CAPCOST"], **dict(_EFP, site_cond=
         "ICALL .EQ. 'G' .AND. N .EQ. 1")),
    dict(tag="y_cap2", call=r"CALL CAPCOST\(NRGN,ICALL,N\)", routines=["CAPCOST"], **dict(_EFP, site_cond=
         "ICALL .EQ. 'G' .AND. N .EQ. 2")),
    dict(tag="y_alf", call=r"IF \(ICALL \.EQ\. 'G'\) CALL ALLFAC\(NRGN\)", routines=["ALLFAC"], **_EFP),
    dict(tag="y_anb", call=r"IF \(ICALL \.EQ\. 'G' \.and\. curiyr\+uhbsyr \.gt\. efpsyr\) &\s*\n\s*CALL ANEWBLD\(NRGN\)",
         routines=["ANEWBLD"], itr=1, **_EFP),
    dict(tag="y_tran", call=r"if \(curiyr\+UHBSYR \.ge\. EFPSYR\) CALL ELTRAN\(NRGN\)", routines=["ELTRAN"], itr=1,
         **_EFP),
    dict(tag="y_dist", call=r"if \(CURIYR\+UHBSYR \.ge\. EFPSYR\) CALL ELDIST\(NRGN\)", routines=["ELDIST"], itr=1,
         **_EFP),
    dict(tag="cp", call=r"IF \(USW_POL \.eq\. 4\) &\s*\n\s*CALL COMPPRC\(NRGN\)", routines=["COMPPRC"], **_EFP),
]
EMM_TARGETS += [
    dict(tag="se", call=r"CALL ELSET\b", file="uefp", home=["uefp", "udaf"], routines=["ELSET"]),
    dict(tag="rv", call=r"IF \(EFPFCRL \.eq\. 1\) CALL REVGAP", file="uefp", home=["uefp", "udaf"],
         routines=["REVGAP"]),
]
EMM_SWAPS = [
    (r"^(\s*)CALL ELECP\s*$", r"\1CONTINUE   ! ORACLE: ECP (AIMMS LP) not run"),
    (r"^(\s*)CALL ELEFD\(CURIYR\)", r"\1CALL EFD_STANDIN(CURIYR)   ! ORACLE: was CALL ELEFD(CURIYR)"),
    # These copy EFD results into NEMS's shared arrays. Skipped so those arrays keep
    # EIA's values from the restart file, which EFP and the stand-in read.
    (r"^(\s*)CALL EMMCAPO\s*$", r"\1CONTINUE   ! ORACLE: EMMCAPO skipped"),
    (r"^(\s*)CALL EMMDSPO\s*$", r"\1CONTINUE   ! ORACLE: EMMDSPO skipped"),
    (r"^(\s*)IF \(FCRL \.EQ\. 1 \.OR\. CURITR \.GT\. MAXITR\)CALL EMMGENO\s*$", r"\1CONTINUE   ! ORACLE: EMMGENO skipped"),
    (r"^(\s*)CALL EMMBODPV\s*$", r"\1CONTINUE   ! ORACLE: EMMBODPV skipped"),
    (r"^(\s*)CALL EMMPRCO\s*$", r"\1CONTINUE   ! ORACLE: EMMPRCO skipped"),
]
# EFD's per-region output and build blocks live in direct-access files, not in
# COMMON, so the stand-in dumps them region by region ("<name>_rNN", tag fs_out).
EMM_REGION_FILES = ["dispout", "bildin"]

MODULES = {
    "comm": dict(build="build", run="run", years=DUMP_YEARS, targets=TARGETS, includes=STATE_INCLUDES,
                 use=None, block_files=STATE_BLOCK_FILES, extra=STATE_EXTRA, decl_files=DECL_FILES,
                 module_text=False),
    "resd": dict(build="build_resd", run="run_resd", years=RESD_DUMP_YEARS, targets=RESD_TARGETS,
                 includes=[], use="R_", block_files=RESD_STATE_BLOCK_FILES, extra=RESD_STATE_EXTRA,
                 decl_files=RESD_DECL_FILES, module_text=True, wide_files=RESD_WIDE_FILES,
                 outside_files=["tranrep"]),
    "emm": dict(build="build_emm", run="run_emm", years=EMM_DUMP_YEARS, targets=EMM_TARGETS, module_text=False,
                sources=["util", "udat", "uldsm", "uefp", "uefd", "uecp", "unugs", "udaf", "ucape", "uread"]),
}
# Industrial: routines are external, sharing MODULE I_ through USE, so as for
# residential the state dump USEs the module. Dumps are the routine-by-routine
# targets below, taken from the final iteration of these years.
IND_DUMP_YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]  # 2019 2020 2021 2025 2026 2027 2030 2040 2050
# CALBSC runs once per industry and region; the dump holds the last one of the year.
IND_TARGETS = [
    dict(tag="bsc", call=r"if \(inddir\.ne\.8 \.and\. inddir\.ne\.12\) CALL CALBSC", nth=1,
         end=r"^\s*END SUBROUTINE CALBSC", before=True, private=[], carried=[], when="inddir.eq.24 .and. indreg.eq.4"),
    dict(tag="stot", call=r"if \(inddir\.ne\.8 \.and\. inddir\.ne\.12\) CALL CALSTOT", nth=1,
         end=r"^\s*END SUBROUTINE CALSTOT", before=True, private=[], carried=[], when="inddir.eq.24 .and. indreg.eq.4"),
    # Single industry and region cases, since each dump holds only one call: food (7) and bulk
    # chemicals (9) have CHP and share biomass boiler fuel, wood products (19) burns biomass,
    # mining (3) is nonmanufacturing (no coal boilers).
    dict(tag="stot7", call=r"if \(inddir\.ne\.8 \.and\. inddir\.ne\.12\) CALL CALSTOT", nth=1,
         end=r"^\s*END SUBROUTINE CALSTOT", before=True, private=[], carried=[], when="inddir.eq.7 .and. indreg.eq.3"),
    dict(tag="stot9", call=r"if \(inddir\.ne\.8 \.and\. inddir\.ne\.12\) CALL CALSTOT", nth=1,
         end=r"^\s*END SUBROUTINE CALSTOT", before=True, private=[], carried=[], when="inddir.eq.9 .and. indreg.eq.3"),
    dict(tag="stot19", call=r"if \(inddir\.ne\.8 \.and\. inddir\.ne\.12\) CALL CALSTOT", nth=1,
         end=r"^\s*END SUBROUTINE CALSTOT", before=True, private=[], carried=[], when="inddir.eq.19 .and. indreg.eq.2"),
    dict(tag="stot3", call=r"if \(inddir\.ne\.8 \.and\. inddir\.ne\.12\) CALL CALSTOT", nth=1,
         end=r"^\s*END SUBROUTINE CALSTOT", before=True, private=[], carried=[], when="inddir.eq.3 .and. indreg.eq.1"),
    dict(tag="bsc3", call=r"if \(inddir\.ne\.8 \.and\. inddir\.ne\.12\) CALL CALBSC", nth=1,
         end=r"^\s*END SUBROUTINE CALBSC", before=True, private=[], carried=[], when="inddir.eq.3 .and. indreg.eq.1"),
    dict(tag="bsc7", call=r"if \(inddir\.ne\.8 \.and\. inddir\.ne\.12\) CALL CALBSC", nth=1,
         end=r"^\s*END SUBROUTINE CALBSC", before=True, private=[], carried=[], when="inddir.eq.7 .and. indreg.eq.3"),
    dict(tag="itot", call=r"CALL INDTOTAL\(INDREG\)", nth=1,
         end=r"^\s*END\s+SUBROUTINE INDTOTAL", before=True, private=[], carried=[], when="inddir.eq.24 .and. indreg.eq.4"),
    dict(tag="itot1", call=r"CALL INDTOTAL\(INDREG\)", nth=1,
         end=r"^\s*END\s+SUBROUTINE INDTOTAL", before=True, private=[], carried=[], when="inddir.eq.1 .and. indreg.eq.1"),
    dict(tag="itot7", call=r"CALL INDTOTAL\(INDREG\)", nth=1,
         end=r"^\s*END\s+SUBROUTINE INDTOTAL", before=True, private=[], carried=[], when="inddir.eq.7 .and. indreg.eq.3"),
    dict(tag="itot8", call=r"CALL INDTOTAL\(INDREG\)", nth=1,
         end=r"^\s*END\s+SUBROUTINE INDTOTAL", before=True, private=[], carried=[], when="inddir.eq.8 .and. indreg.eq.2"),
    dict(tag="itot12", call=r"CALL INDTOTAL\(INDREG\)", nth=1,
         end=r"^\s*END\s+SUBROUTINE INDTOTAL", before=True, private=[], carried=[], when="inddir.eq.12 .and. indreg.eq.1"),
    dict(tag="itot16", call=r"CALL INDTOTAL\(INDREG\)", nth=1,
         end=r"^\s*END\s+SUBROUTINE INDTOTAL", before=True, private=[], carried=[], when="inddir.eq.16 .and. indreg.eq.4"),
    dict(tag="cinit", call=r"CALL COGINIT\(INDREG\)", nth=0,
         end=r"^\s*END\s+SUBROUTINE COGINIT", before=True, private=[], carried=[], when="inddir.eq.21 .and. indreg.eq.4"),
    dict(tag="cinit7", call=r"CALL COGINIT\(INDREG\)", nth=0,
         end=r"^\s*END\s+SUBROUTINE COGINIT", before=True, private=[], carried=[], when="inddir.eq.7 .and. indreg.eq.3"),
    dict(tag="cinit9", call=r"CALL COGINIT\(INDREG\)", nth=0,
         end=r"^\s*END\s+SUBROUTINE COGINIT", before=True, private=[], carried=[], when="inddir.eq.9 .and. indreg.eq.3"),
    dict(tag="cinit19", call=r"CALL COGINIT\(INDREG\)", nth=0,
         end=r"^\s*END\s+SUBROUTINE COGINIT", before=True, private=[], carried=[], when="inddir.eq.19 .and. indreg.eq.2"),
    dict(tag="ecog", call=r"call evalcogen\(0,CURIYR\+BASEYR-1\)", nth=0,
         end=r"^\s*END\s+SUBROUTINE EvalCogen", before=True, private=[], carried=[], when="inddir.eq.21 .and. indreg.eq.4"),
    dict(tag="ecog7", call=r"call evalcogen\(0,CURIYR\+BASEYR-1\)", nth=0,
         end=r"^\s*END\s+SUBROUTINE EvalCogen", before=True, private=[], carried=[], when="inddir.eq.7 .and. indreg.eq.3"),
    dict(tag="ecog9", call=r"call evalcogen\(0,CURIYR\+BASEYR-1\)", nth=0,
         end=r"^\s*END\s+SUBROUTINE EvalCogen", before=True, private=[], carried=[], when="inddir.eq.9 .and. indreg.eq.3"),
    dict(tag="ecog19", call=r"call evalcogen\(0,CURIYR\+BASEYR-1\)", nth=0,
         end=r"^\s*END\s+SUBROUTINE EvalCogen", before=True, private=[], carried=[], when="inddir.eq.19 .and. indreg.eq.2"),
    dict(tag="cgen", call=r"CALL CALGEN\b", nth=0,
         end=r"^\s*END\s+SUBROUTINE CALGEN", before=True, private=[], carried=[], when="inddir.eq.21 .and. indreg.eq.4"),
    dict(tag="cgen7", call=r"CALL CALGEN\b", nth=0,
         end=r"^\s*END\s+SUBROUTINE CALGEN", before=True, private=[], carried=[], when="inddir.eq.7 .and. indreg.eq.3"),
    dict(tag="cgen9", call=r"CALL CALGEN\b", nth=0,
         end=r"^\s*END\s+SUBROUTINE CALGEN", before=True, private=[], carried=[], when="inddir.eq.9 .and. indreg.eq.3"),
    dict(tag="cgen19", call=r"CALL CALGEN\b", nth=0,
         end=r"^\s*END\s+SUBROUTINE CALGEN", before=True, private=[], carried=[], when="inddir.eq.19 .and. indreg.eq.2"),
    dict(tag="cgen1", call=r"CALL CALGEN\b", nth=0,
         end=r"^\s*END\s+SUBROUTINE CALGEN", before=True, private=[], carried=[], when="inddir.eq.1 .and. indreg.eq.1"),
]
IND_STATE_BLOCK_FILES = ["indrep", "indout", "cogen", "bifurc"]
# Module-level arrays and scalars of MODULE I_ that the ported routines read or write.
IND_STATE_EXTRA = ["inddir", "indreg", "iyr", "curiyr", "curcalyr", "ibyr", "ibyr2", "lastcalyr", "curitr",
                   "BSCIBYR", "beff", "PRCX", "PRCXIBYR", "PRCXYR", "MAINFUELS", "BSFUELSHR", "BSSHR", "Boiler_Fuel_List", "HPbeff",
                   # CALSTOT
                   "stemcur", "biosteam", "biosteamlag", "prodvx", "prodvxlag", "noncogsteam", "noncogfossteam",
                   "CogBoilFuel", "FuelFosSteam", "FosFuelSteamSize", "sizeshr", "CALIBIBYR_FOS", "CALIBIBYR_BIO",
                   "BOILIBYR", "STEMCURIBYR", "COGSTEAMIBYR", "BIOSTEAMIBYR", "ENSQTY", "ENPRQTY", "cogsteamhist",
                   "maxcogyr", "baseyr", "numflchp", "yr",
                   "cogthr", "cogelf", "coggrd", "cogcap", "coggen", "genfuel", "rptcap", "rptgen", "cogsteam",
                   # INDTOTAL
                   "ENPMQTY", "ENPIQTY", "ENBQTY", "BYPBSCI", "BYPBSCR", "BYPBSCM", "CFELQ", "ELOWN", "ELSALE",
                   "REFCON", "ELOWNX", "ELSALEX", "XELIN", "XELINSHR", "QTYMAIN", "QTYINTR", "QTYRENW", "indnum",
                   # COGINIT
                   "nadds"] + list(f"cogadd%{c}" for c in ("year", "industry", "censusdiv", "fuelind", "gen", "cap", "thr", "elc", "grd")) + [
                   # EVALCOGEN
                   "nsys", "nload", "CapCostYearly", "CheatRateYearly", "OverAllEffYearly", "CHeatRate", "CogSizeKW",
                   "CapFac", "maxRegCHPutil", "RegCHPutil", "QELAS", "CogFuelPrice", "CogElecPrice", "CapCostMultStart",
                   "CapCostMultEnd", "CapCostMult", "MC_RMTCM10Y", "MC_CPI", "AcceptFrac", "AcceptFrac2",
                   "CogCapCostKW", "OverAllEff", "ElecGenEff", "ElecSizeMWH", "FuelUse", "PowerSteam", "SteamOutput",
                   "EBoilEff", "CogSys", "FuelCost", "ExistFuelUse", "ExistFuelCost", "ElecValue", "IncrFuelCost",
                   "OperProfit", "Investment", "CPayBack", "EconFrac",
                   # CALGEN
                   "lookahead", "ijumpyr", "ieyr", "DollarYearCHP", "StandByFrac", "CARBSHR", "CARBSHR_AB", "QGFIN", "QELIN",
                   "aGFIN", "pGFIN", "aELIN", "SteamSeg_Food", "SteamSeg_Paper", "SteamSeg_Chem", "SteamSeg_Steel",
                   "SteamSeg_Other", "stemcurlag", "IFSBYP", "IFSLOCBY", "BYPSTMM", "BYPSTMI", "BYPSTMR", "BYPSTM",
                   "penetration", "techstrtyr", "hitech", "RegCHPutil", "maxRegCHPutil", "ibyr2", "ENBQTY", "ENPIQTY", "MC_JPGDP"]
IND_DECL_FILES = ["parametr", "indrep", "indout", "cogen", "indepm", "bifurc", "ghgrep", "qblk", "apq",
                  "ampblk", "mpblk", "eusprc", "macout", "ncntrl", "emmparm", "epmmpblk"]
MODULES["ind"] = dict(build="build_ind", run="run_ind", years=IND_DUMP_YEARS, targets=IND_TARGETS,
                      includes=[], use="I_", block_files=IND_STATE_BLOCK_FILES, extra=IND_STATE_EXTRA,
                      decl_files=IND_DECL_FILES, module_text=True, module_name="I_", decls_only=True)
CFG = MODULES["comm"]

# Spaces are allowed around the * ("REAL *4" in efpnd).
TYPE_RE = re.compile(r"^(real\s*\*\s*8|double precision|real\s*\*\s*4|real|integer\s*\*\s*1|integer\s*\*\s*2"
                     r"|integer\s*\*\s*4|integer\s*\*\s*8|integer"
                     r"|logical(?:\*\d+)?|character(?:\s*\*\s*(?:\(\s*[\w*]+\s*\)|\d+))?)(?![\w*])(.*)", re.I)


def statements(text):
    buf = ""
    for line in text.splitlines():
        line = line.split("!", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.endswith("&"):
            buf += line[:-1] + " "
            continue
        yield (buf + line).strip()
        buf = ""


def split_top(s):
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def declarations(text):
    """{name: (type, rank)} from type statements and COMMON dimension lists."""
    out = {}
    for st in statements(text):
        m = TYPE_RE.match(st)
        if m and not re.match(r"\s*function", m.group(2), re.I):
            t = m.group(1).lower().replace(" ", "")
            body = m.group(2).split("::", 1)[-1]
            for ent in split_top(body):
                em = re.match(r"([\w$]+)\s*(?:\*\s*\d+)?\s*(\((.*)\))?", ent)
                if em:
                    rank = len(split_top(em.group(3))) if em.group(2) else 0
                    prev = out.get(em.group(1).lower(), (t, 0))
                    out[em.group(1).lower()] = (t, max(rank, prev[1]))
        cm = re.match(r"common\s*/\s*\w+\s*/(.*)", st, re.I)
        if cm:
            for ent in split_top(cm.group(1)):
                em = re.match(r"([\w$]+)\s*(\((.*)\))?", ent)
                if em and em.group(2):
                    t = out.get(em.group(1).lower(), ("?", 0))[0]
                    out[em.group(1).lower()] = (t, len(split_top(em.group(3))))
    return out


def type_code(t, name):
    if t == "?":  # implicit typing
        t = "integer" if name[0].lower() in "ijklmn" else "real"
    if t.startswith("character"):
        m = re.match(r"character\*(\d+)$", t)
        return f"S{m.group(1)}" if m else None  # fixed-length text, e.g. CostTrend
    return {"real*8": "f8", "doubleprecision": "f8", "real*4": "f4", "real": "f4",
            "integer*1": "i1", "integer*2": "i2", "integer*4": "i4", "integer*8": "i8", "integer": "i4"}.get(
        t, "i4" if t.startswith("logical") else None)


def common_names(text):
    names = []
    for st in statements(text):
        cm = re.match(r"common\s*/\s*\w+\s*/(.*)", st, re.I)
        if cm:
            names += [re.match(r"[\w$]+", e).group(0) for e in split_top(cm.group(1))]
    return names


# Components of the derived-type array COGADD (planned CHP builds); dumped as plain arrays.
COMPONENT_DECLS = {f"cogadd%{c}": ("integer" if c in ("year", "industry", "censusdiv", "fuelind") else "real", 1)
                   for c in ("year", "industry", "censusdiv", "fuelind", "gen", "cap", "thr", "elc", "grd")}


def dump_call(tag, name, t, rank):
    code = type_code(t, name)
    if code is None:
        return None
    if code.startswith("S"):
        # Text arrays carry a hidden length argument, so they need a routine
        # that declares them as text (odump_c in stubs.f90).
        lb = f"lbound({name})" if rank else "0"
        ub = f"ubound({name})" if rank else "0"
        return (f"      call odump_c('{tag}', '{name.lower().replace('%', '_')}', CURIYR, {name}, sizeof({name}), '{code}', "
                f"{rank}, {lb}, {ub})")
    if rank == 0:
        return f"      call odump('{tag}', '{name.lower().replace('%', '_')}', CURIYR, {name}, sizeof({name}), '{code}', 0, 0, 0)"
    return (f"      call odump('{tag}', '{name.lower().replace('%', '_')}', CURIYR, {name}, sizeof({name}), '{code}', "
            f"{rank}, lbound({name}), ubound({name}))")


def module_r_(source_text, name="R_"):
    """The MODULE R_ block of resd.f (or I_ of ind.f): its declarations and its shared arrays."""
    m = re.search(r"^\s*MODULE " + name + r"\s*$(.*?)^\s*END MODULE " + name, source_text, re.I | re.M | re.S)
    text = m.group(1)
    names = common_names(text)
    for st in statements(text):
        a = re.match(r"real\*\d\s*,\s*allocatable\s*::(.*)", st, re.I)
        if a:
            names += [re.match(r"[\w$]+", e).group(0) for e in split_top(a.group(1))]
    return text, names


def routine_bodies(source_text):
    """{lowercase name: body text} for every routine and function in the file."""
    out = {}
    # Routines nest (all of resd.f sits inside RESD), so find each one's own end.
    for m in re.finditer(r"^[ \t]*(?:REAL(?:\*4)?[ \t]+)?(?:SUBROUTINE|FUNCTION)[ \t]+(\w+)", source_text, re.I | re.M):
        e = re.compile(rf"^[ \t]*END[ \t]+(?:SUBROUTINE|FUNCTION)[ \t]+{m.group(1)}\b", re.I | re.M).search(source_text, m.end())
        if e:
            body = source_text[m.end():e.start()]
            out[m.group(1).lower()] = "\n".join(l.split("!", 1)[0] for l in body.splitlines())
    return out


def routine_idents(source_text, routines):
    """Lowercase identifiers used in the named routines and everything they call."""
    bodies = routine_bodies(source_text)
    used, todo, seen = set(), [r.lower() for r in routines], set()
    while todo:
        r = todo.pop()
        if r in seen:
            continue
        seen.add(r)
        words = {w.lower() for w in re.findall(r"[A-Za-z_]\w*", bodies[r])}
        used |= words
        todo += [w for w in words if w in bodies and w not in seen and w != "resd"]
    return used


def write_state_routine(inc_dir, source_text=None):
    decls = {}
    for n in CFG["decl_files"]:
        decls.update(declarations((inc_dir / n).read_text(encoding="latin-1")))
    names = []
    for n in CFG["block_files"]:
        names += common_names((inc_dir / n).read_text(encoding="latin-1"))
    if CFG["module_text"]:
        mtext, mnames = module_r_(source_text, CFG.get("module_name", "R_"))
        decls.update(declarations(mtext))
        if not CFG.get("decls_only"):  # ind: only the names listed in extra, not all of I_
            names += mnames
    names += CFG["extra"]
    decls.update(COMPONENT_DECLS)

    def calls_for(subset):
        cs = [c for c in (dump_call("'//tag//'", n, *decls.get(n.lower(), ("?", 0))) for n in {s.lower(): s for s in subset}.values()) if c]
        return [c.replace("''//tag//''", "tag") for c in cs]

    calls = calls_for(names)
    extra_routine = ""
    if CFG["module_text"] and "wide_files" in CFG:
        # A full residential dump is about 170 MB. Around a target, dump only the
        # shared arrays its routines mention; the full set is kept for 'final'.
        wide = list(names)
        for n in CFG["wide_files"]:
            wide += common_names((inc_dir / n).read_text(encoding="latin-1"))
        # Blocks only some routines include (tranrep) clash with R_, so their
        # arrays go through a second routine that includes them instead.
        outside = []
        for n in CFG["outside_files"]:
            decls.update(declarations((inc_dir / n).read_text(encoding="latin-1")))
            outside += common_names((inc_dir / n).read_text(encoding="latin-1"))
        blocks, xblocks = [], []
        for tg in map(as_dict, CFG["targets"]):
            used = routine_idents(source_text, tg["routines"])
            sub = calls_for([n for n in wide if n.lower() in used])
            xsub = calls_for([n for n in outside if n.lower() in used])
            cond = f"if (tag == '{tg['tag']}_in' .or. tag == '{tg['tag']}_out') then"
            if xsub:
                sub.append("        call oracle_state_x(tag)")
                xblocks.append(f"      {cond}\n" + "\n".join(xsub) + "\n      endif")
            blocks.append(f"      {cond}\n" + "\n".join(sub) + "\n        return\n      endif")
        calls = blocks + calls
        xinc = "\n".join(f"      include '{n}'" for n in ["parametr", "ncntrl"] + CFG["outside_files"])
        extra_routine = f"""
      subroutine oracle_state_x(tag)
      implicit none
{xinc}
      character(*) tag
{chr(10).join(xblocks)}
      end subroutine oracle_state_x
"""
    years = ", ".join(map(str, CFG["years"]))
    inc = "\n".join(f"      include '{n}'" for n in CFG["includes"])
    if CFG["use"]:
        inc = f"      use {CFG['use']}\n      implicit none\n" + inc  # USE must come first
    else:
        inc = "      implicit none\n" + inc
    body = "\n".join(calls)
    (BUILD / "oracle_state.f90").write_text(f"""! Generated by hooks.py. Do not edit.
      subroutine oracle_state(tag)
{inc}
      character(*) tag
      integer, parameter :: years({len(CFG["years"])}) = (/ {years} /)
      if (tag(1:1) == 'f') then
        if (CURIYR .ne. {FIRST_YEAR} .or. CURITR .ne. 1) return
      else
        if (FCRL .ne. 1 .or. .not. any(years == CURIYR)) return
      endif
{body}
      end subroutine oracle_state
{extra_routine}""")
    return len(calls)


# Variables the dump hooks must leave out: names the 2026 source declares where the hook sits but another
# release does not (ORACLE_SKIP_VARS="applyramp,datactrservpenetration", found from the compiler's
# "has no IMPLICIT type" errors; see docs/aeo_diff2.md).
SKIP_VARS = {v.strip().lower() for v in os.environ.get("ORACLE_SKIP_VARS", "").split(",") if v.strip()}


def private_dumps(tag, names, src_decls):
    names = [n for n in names if n.lower() not in SKIP_VARS]
    return [c for c in (dump_call(tag, n, *src_decls.get(n.lower(), ("?", 0))) for n in names) if c]


def as_dict(target):
    if isinstance(target, dict):
        name = re.search(r"CALL\s+(\w+)", target["call"], re.I).group(1)
        return dict(dict(nth=0, end=None, private=[], carried=[], before=False, routines=[name],
                         file="util", region=False, itr=None, cond=None, site_cond=None), **target)
    tag, call_re, end_re, private, carried = target
    before = bool(end_re) and end_re.startswith("before:")  # commercial targets mark "dump before this line" in the pattern
    if before:
        end_re = end_re.removeprefix("before:")
    return dict(tag=tag, call=call_re, end=end_re, private=private, carried=carried, nth=0, before=before)


def instrument(comm_path: Path, upstream: Path):
    text = comm_path.read_text(encoding="latin-1")
    # Private arrays may be declared in an include file (EmissionFactor) rather than in the source itself.
    src_decls = {}
    for n in CFG["decl_files"]:
        src_decls.update(declarations((upstream / "includes" / n).read_text(encoding="latin-1")))
    src_decls.update(declarations(text))
    comm = CFG is MODULES["comm"]
    for tg in map(as_dict, CFG["targets"]):
        tag, call_re, end_re, private, carried = tg["tag"], tg["call"], tg["end"], tg["private"], tg["carried"]
        m = list(re.finditer(r"^(\s*)(" + call_re + r")", text, re.I | re.M))[tg["nth"]]
        ind = m.group(1)
        first = comm and tag in FIRST_CALL
        first_in = f"{ind}CALL ORACLE_STATE('f{tag}_in')\n" if first else ""
        first_out = f"\n{ind}CALL ORACLE_STATE('f{tag}_out')" if first else ""
        guard = f"IF ({tg['when']}) " if tg.get("when") else ""  # dump one industry and region only
        text = (text[:m.start()] + f"{ind}{guard}CALL ORACLE_STATE('{tag}_in')\n{first_in}{ind}{m.group(2)}\n"
                f"{ind}{guard}CALL ORACLE_STATE('{tag}_out'){first_out}" + text[m.end():])
        years = ", ".join(map(str, CFG["years"]))
        if not private and not carried:
            continue
        lines = [f"      IF (FCRL .EQ. 1 .AND. ANY((/ {years} /) == CURIYR)) THEN"]
        lines += private_dumps(f"{tag}_out", private + carried, src_decls)
        lines.append(f"      ELSE IF (ANY((/ {years} /) == CURIYR)) THEN")
        lines += private_dumps(f"{tag}_pre", carried, src_decls)
        lines.append("      ENDIF")
        e = re.search(end_re, text, re.I | re.M)
        if tg["before"]:
            line_start = text.rindex("\n", 0, e.start()) + 1
            text = text[:line_start] + "\n".join(lines) + "\n" + text[line_start:]
        else:
            line_end = text.index("\n", e.end())
            text = text[:line_end + 1] + "\n".join(lines) + "\n" + text[line_end + 1:]
    if comm:
        for tag, anchor_re, private in PROBES:
            lines = [f"      IF (CURIYR .EQ. {FIRST_YEAR} .AND. CURITR .EQ. 1) THEN",
                     f"      CALL ORACLE_STATE('{tag}_out')"]
            lines += private_dumps(f"{tag}_out", private, src_decls)
            lines.append("      ENDIF")
            e = re.search(anchor_re, text, re.I | re.M)
            at = text.index("\n", e.end()) + 1
            text = text[:at] + "\n".join(lines) + "\n" + text[at:]
    comm_path.write_text(text, encoding="latin-1")


def emm_bodies(text):
    """{lowercase name: (body, include list)} for every routine in EMM's files.
    EMM routines end in a bare END, so a body runs to the next routine's start."""
    heads = list(re.finditer(r"^[ \t]*(?:(?:REAL|INTEGER|LOGICAL)(?:\*\d)?[ \t]+)?(?:SUBROUTINE|FUNCTION)[ \t]+(\w+)",
                             text, re.I | re.M))
    out = {}
    for i, m in enumerate(heads):
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        incs = [n.lower() for n in re.findall(r"(?im)^\s*include\s*'(\w+)'", body)]
        out.setdefault(m.group(1).lower(), ("\n".join(l.split("!", 1)[0] for l in body.splitlines()), incs))
    return out


def emm_closure(bodies, routines):
    """Identifiers and includes used by the routines and everything they call."""
    used, incs, todo, seen = set(), [], [r.lower() for r in routines], set()
    while todo:
        r = todo.pop(0)
        if r in seen or r not in bodies:
            continue
        seen.add(r)
        body, rincs = bodies[r]
        words = {w.lower() for w in re.findall(r"[A-Za-z_][\w$]*", body)}
        used |= words
        incs += [n for n in rincs if n not in incs]
        todo += sorted(w for w in words if w in bodies and w not in seen)
    return used, incs


def nested_includes(n, inc_dir, seen=None):
    seen = set() if seen is None else seen
    for m in re.findall(r"(?im)^\s*include\s*'(\w+)'", (inc_dir / n).read_text(encoding="latin-1")):
        if m.lower() not in seen:
            seen.add(m.lower())
            nested_includes(m.lower(), inc_dir, seen)
    return seen


def include_list_errors(incs):
    """Include files named in gfortran's errors for a routine with just these
    includes (about 5 s for EMM's), or [] if it compiles."""
    test = BUILD / "_inc_test.f90"
    test.write_text("      subroutine t\n      implicit none\n" + "".join(f"      include '{n}'\n" for n in incs)
                    + "      end subroutine t\n")
    r = subprocess.run(["gfortran", "-fsyntax-only", "-ffree-line-length-none", "-fdec", "-Iinc", test.name],
                       cwd=BUILD, capture_output=True, text=True)
    test.unlink()
    if r.returncode == 0:
        return []
    return [m.lower() for m in re.findall(r"^(\w+):\d+:\d+:", r.stderr, re.M)] or ["?"]


def compiling_includes(incs, inc_dir):
    """incs minus any include another one already pulls in, then minus whichever
    include gfortran's errors point at, until the list compiles."""
    incs = [n for n in incs if (inc_dir / n).exists()]
    inner = set()
    for n in incs:
        inner |= nested_includes(n, inc_dir)
    incs = [n for n in incs if n not in inner or n == "parametr"]
    while True:
        bad = include_list_errors(incs)
        if not bad:
            return incs
        culprit = next((n for n in reversed(incs) if n == bad[0] or bad[0] in nested_includes(n, inc_dir)), incs[-1])
        if culprit in ("parametr", "ncntrl"):
            culprit = incs[-1]
        print(f"  dropping include {culprit} ({bad[0]} does not compile with the others)", flush=True)
        incs.remove(culprit)


def local_commons(bodies, routines):
    """COMMON blocks declared inside routine bodies rather than in an include
    (LDSM's hourly load shapes, /REGSYSLD/ and /EUSYSLD/; EFP's /EFPIT/ and others).
    Returns (declaration lines, member names, {member: (type, rank)}), first
    declaration of each block wins."""
    lines, names, decls, seen = [], [], {}, set()
    for r in routines:
        if r not in bodies:
            continue
        body = bodies[r][0]
        bdecl = declarations(body)
        texts = {}
        for st in statements(body):
            m = TYPE_RE.match(st)
            if m and not re.match(r"\s*function", m.group(2), re.I):
                for ent in split_top(m.group(2).split("::", 1)[-1]):
                    em = re.match(r"([\w$]+)\s*(?:\*\s*\d+)?\s*(\(.*\))?", ent)
                    if em:
                        texts[em.group(1).lower()] = f"{m.group(1)} {ent.strip()}"
        for st in statements(body):
            cm = re.match(r"common\s*/\s*([\w$]+)\s*/(.*)", st, re.I)
            if not cm or cm.group(1).lower() in seen:
                continue
            members = [re.match(r"[\w$]+", e).group(0) for e in split_top(cm.group(2))]
            if not all(v.lower() in texts for v in members):
                continue  # typed implicitly or in an include: leave it to the include path
            seen.add(cm.group(1).lower())
            lines += [f"      {texts[v.lower()]}" for v in members]
            lines.append(f"      COMMON /{cm.group(1)}/ " + ", ".join(members))
            names += members
            decls.update({v.lower(): bdecl[v.lower()] for v in members})
    return lines, names, decls


def emm_dump_routine(name, incs, inc_dir, used, tag_expr, suffix=None, local=None):
    """A routine that includes `incs` and dumps every COMMON member in them that
    `used` mentions (all members when used is None), plus the members of `local`,
    COMMON blocks declared in the routines themselves (see local_commons)."""
    incs = ["parametr"] + [n for n in incs if n != "parametr"]
    if "ncntrl" not in incs:
        incs.insert(1, "ncntrl")
    incs = compiling_includes(incs, inc_dir)
    files = list(incs)
    for n in incs:
        files += sorted(nested_includes(n, inc_dir) - set(files))
    decls, names = {}, []
    for n in files:
        t = (inc_dir / n).read_text(encoding="latin-1")
        decls.update(declarations(t))
        names += [v for v in common_names(t) if used is None or v.lower() in used]
        # An EQUIVALENCE alias of a COMMON member is shared too (QELINOUT = QELINP
        # in indout), but no COMMON statement names it.
        for a, b in re.findall(r"(?im)^\s*equivalence\s*\(\s*([\w$]+)\s*(?:\([^)]*\))?\s*,\s*([\w$]+)", t):
            names += [v for v in (a, b) if used is not None and v.lower() in used]
    local_lines = []
    if local:
        local_lines, lnames, ldecls = local
        known = {v.lower() for v in names}
        clash = [v for v in lnames if v.lower() in known or v.lower() in decls]
        if clash:  # an include declares the same name: skip the block rather than break the build
            print(f"  {name}: local COMMON members also in includes, skipped: {clash}")
            local_lines = []
        else:
            names += lnames
            decls.update(ldecls)
    calls = []
    for v in {s.lower(): s for s in names}.values():
        c = dump_call("@TAG@", v, *decls.get(v.lower(), ("?", 0)))
        if c:
            c = c.replace("'@TAG@'", tag_expr)
            if suffix:
                c = c.replace(f"'{v.lower()}'", f"'{v.lower()}'//{suffix}", 1)
            calls.append(c)
    inc = "\n".join(f"      include '{n}'" for n in incs)
    arg = "tag, irg" if suffix else "tag"
    extra = "      integer irg\n      character(4) rsuf\n" if suffix else ""
    pre = "      write(rsuf, '(a,i2.2)') '_r', irg\n" if suffix else ""
    loc = "".join(f"{l}\n" for l in local_lines)
    src = (f"      subroutine {name}({arg})\n      implicit none\n{inc}\n{loc}      character(*) tag\n{extra}{pre}"
           + "\n".join(calls) + f"\n      end subroutine {name}\n")
    return src, len(calls), incs


def write_state_routine_emm(inc_dir):
    by_file = {s: emm_bodies((BUILD / f"{s}.f90").read_text(encoding="latin-1")) for s in CFG["sources"]}
    years = ", ".join(map(str, CFG["years"]))
    routines, branches, rg_branches, total = [], [], [], 0
    all_used, all_incs = set(), []
    regions = ", ".join(map(str, EMM_DUMP_REGIONS))
    for tg in map(as_dict, CFG["targets"]):
        bodies = {}
        for s in tg["home"]:
            bodies.update(by_file[s])
        used, incs = emm_closure(bodies, tg["routines"])
        if tg["file"] == "util":
            all_used |= used
            all_incs += [n for n in incs if n not in all_incs]
        name = f"oracle_state_{tg['tag']}"
        reached = [r for r in bodies if r in used or r in {x.lower() for x in tg["routines"]}]
        local = local_commons(bodies, reached)
        if tg["region"]:
            src, n, _ = emm_dump_routine(name, incs, inc_dir, used, "tag", suffix="rsuf", local=local)
        else:
            src, n, _ = emm_dump_routine(name, incs, inc_dir, used, "tag", local=local)
        routines.append(src)
        when = "CURITR .eq. 1" if tg["itr"] == 1 else "FCRL .eq. 1"
        if tg["cond"]:
            when += f" .and. ({tg['cond']})"
        if tg["region"] is True:
            when += f" .and. any(regions == RNB) .and. any(ryears == CURIYR)"
            call = f"call {name}(tag, int(RNB))"
        elif tg["region"] and tg.get("few"):
            when += f" .and. irg == {EMM_DUMP_REGIONS[0]} .and. CURIYR == {EMM_REGION_YEARS[1]}"
            call = f"call {name}(tag, irg)"
        elif tg["region"]:  # passed in by the call: ORACLE_STATE_RG(tag, region)
            when += f" .and. any(regions == irg) .and. any(ryears == CURIYR)"
            call = f"call {name}(tag, irg)"
        else:
            call = f"call {name}(tag)"
            if tg.get("ryears_only"):
                when += " .and. any(ryears == CURIYR)"
        branch = (f"      if (tag == '{tg['tag']}_in' .or. tag == '{tg['tag']}_out') then\n"
                  f"        if ({when}) {call}\n        return\n      endif")
        (rg_branches if isinstance(tg["region"], str) else branches).append(branch)
        total += n
    src, n, _ = emm_dump_routine("oracle_state_final", all_incs, inc_dir, all_used, "tag")
    routines.append(src)
    # Per-region EFD output and build blocks, called from efd_standin.f90.
    region_names = set()
    for f in EMM_REGION_FILES:
        region_names |= {v.lower() for v in common_names((inc_dir / f).read_text(encoding="latin-1"))}
    rsrc, rn, _ = emm_dump_routine("oracle_region_dump", ["emmparm", "control"] + EMM_REGION_FILES, inc_dir,
                                   region_names, "tag", suffix="rsuf")
    routines.append(rsrc)
    body = "\n".join(branches)
    rg_body = "\n".join(rg_branches)
    (BUILD / "oracle_state.f90").write_text(f"""! Generated by hooks.py. Do not edit.
      subroutine oracle_state(tag)
      implicit none
      include 'parametr'
      include 'ncntrl'
      include 'emmparm'
      include 'dsmdimen'
      include 'dsmhelm'
      character(*) tag
      integer, parameter :: years({len(CFG["years"])}) = (/ {years} /)
      integer, parameter :: regions({len(EMM_DUMP_REGIONS)}) = (/ {regions} /)
      integer, parameter :: ryears({len(EMM_REGION_YEARS)}) = (/ {", ".join(map(str, EMM_REGION_YEARS))} /)
      if (.not. any(years == CURIYR)) return
{body}
      if (tag == 'final' .and. FCRL .eq. 1) call oracle_state_final(tag)
      end subroutine oracle_state

      subroutine oracle_state_rg(tag, irg)
      implicit none
      include 'parametr'
      include 'ncntrl'
      character(*) tag
      integer irg
      integer, parameter :: regions({len(EMM_DUMP_REGIONS)}) = (/ {regions} /)
      integer, parameter :: ryears({len(EMM_REGION_YEARS)}) = (/ {", ".join(map(str, EMM_REGION_YEARS))} /)
{rg_body}
      end subroutine oracle_state_rg

      subroutine oracle_region(irg)
      implicit none
      include 'parametr'
      include 'ncntrl'
      integer irg
      integer, parameter :: years({len(CFG["years"])}) = (/ {years} /)
      if (FCRL .ne. 1 .or. .not. any(years == CURIYR)) return
      call oracle_region_dump('fs_out', irg)
      end subroutine oracle_region

{"".join(routines)}""")
    return total + n + rn


def instrument_emm(util_path: Path):
    """Swap the solves in util.f90, and wrap each target's call in its own file
    (uldsm.f90 for LDSM routines), all in the build folder."""
    texts = {"util": util_path.read_text(encoding="latin-1")}
    for pat, repl in EMM_SWAPS:
        texts["util"], k = re.subn(pat, repl, texts["util"], count=1, flags=re.I | re.M)
        assert k == 1, pat
    for tg in map(as_dict, CFG["targets"]):
        f = tg["file"]
        if f not in texts:
            texts[f] = (BUILD / f"{f}.f90").read_text(encoding="latin-1")
        text = texts[f]
        m = list(re.finditer(r"^(\s*)(" + tg["call"] + r")", text, re.I | re.M))[tg["nth"]]
        ind = m.group(1).lstrip("\n")
        if isinstance(tg["region"], str):
            hook = lambda side: ((f"IF ({tg['site_cond']}) " if tg['site_cond'] else "")
                                 + f"CALL ORACLE_STATE_RG('{tg['tag']}_{side}', INT({tg['region']}))")
        else:
            hook = lambda side: f"CALL ORACLE_STATE('{tg['tag']}_{side}')"
        texts[f] = (text[:m.start()] + f"\n{ind}{hook('in')}\n{ind}{m.group(2)}\n"
                    f"{ind}{hook('out')}" + text[m.end():])
    util_path.write_text(texts.pop("util"), encoding="latin-1")
    for f, text in texts.items():
        (BUILD / f"{f}.f90").write_text(text, encoding="latin-1")


def make_dirs():
    """Create the dump folders and drop old index files (odump appends to them)."""
    sys.path.insert(0, str(HERE))
    from cache import link_out
    link_out(next(k for k, v in MODULES.items() if v is CFG))
    dirs = [RUN / "out" / "state" / "final" / str(CFG["years"][-1])]
    for tg in map(as_dict, CFG["targets"]):
        for side in ("in", "out", "pre"):
            dirs += [RUN / "out" / "state" / f"{tg['tag']}_{side}" / str(y) for y in CFG["years"]]
        if CFG is MODULES["comm"] and tg["tag"] in FIRST_CALL:
            dirs += [RUN / "out" / "state" / f"f{tg['tag']}_{side}" / str(FIRST_YEAR) for side in ("in", "out")]
    if CFG is MODULES["comm"]:
        dirs += [RUN / "out" / "state" / f"{tag}_out" / str(FIRST_YEAR) for tag, *_ in PROBES]
    if CFG is MODULES["emm"]:
        dirs += [RUN / "out" / "state" / "fs_out" / str(y) for y in CFG["years"]]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.txt").unlink(missing_ok=True)


if __name__ == "__main__":
    upstream, src = Path(os.path.abspath(sys.argv[1])), Path(sys.argv[2])
    CFG = MODULES[sys.argv[3] if len(sys.argv) > 3 else "comm"]
    BUILD, RUN = WORK / CFG["build"], WORK / CFG["run"]
    if CFG is MODULES["emm"]:
        n = write_state_routine_emm(upstream / "includes")
        instrument_emm(src)
    else:
        n = write_state_routine(upstream / "includes", src.read_text(encoding="latin-1"))
        instrument(src, upstream)
    make_dirs()
    print(f"hooks: {n} shared arrays per state dump, {len(CFG['targets'])} routine(s) instrumented")
