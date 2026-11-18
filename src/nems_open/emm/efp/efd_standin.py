"""The EFD stand-in, in Python: each region's dispatch results for EFP.

Same values as oracle/efd_standin.f90, operation by operation in REAL*4, so a Python
EFP run gets the block the oracle's EFP saw. EMM's dispatch LP runs in AIMMS,
which we do not have; the stand-in fills each region's DISPOUT block from EIA's
regional totals in the restart file where they exist and plausible values where
not (SCOPE.md, "EFP oracle input stand-ins"). Units as in DISPOUT: million 1987
dollars, MWh. Once our own dispatch LP fills this block, it replaces this.
"""

import numpy as np

f32, f64 = np.float32, np.float64

# Stand-in constants (efd_standin.f90)
OWNSHR = [f32(0.8), f32(0.2), f32(0.9), f32(0.05), f32(0.05)]  # EFD owners 1-5 from EIA's 2 groups
OWNSRC = [1, 1, 2, 2, 2]
VOM, FOM, PNUC, PTRADE, PALLW = f32(2.0), f32(8.0), f32(0.4), f32(30.0), f32(0.01)
EFD_D_CAP, EFD_D_OWN, EFD_D_NFL, EFD_D_MSP = 54, 5, 60, 4


# UEFDOUT fuel-use arrays -> the loop's power-sector fuel (QBLK/q**el, MPBLK/p**el suffix) that moves them
FUEL_OF = {"uflclnr": "cl", "uflgfnr": "ng", "uflginr": "ng", "uflgcnr": "ng", "ufldsnr": "ds",
           "uflrlnr": "rs", "uflrhnr": "rs", "uflurnr": "ur"}
PRICE_OF = {"uprclnr": "cl", "uprngnr": "ng", "uprdsnr": "ds", "uprrsnr": "rs"}


def block(snap, iyr: int, irg: int, uiuf: int, efd_d_mvs: int, adjust: dict | None = None) -> dict:
    """The stand-in fields of region irg's DISPOUT block in year index iyr (1-based,
    Fortran's CURIYR), as {lowercase name: value}. snap: the restart file
    (nems_open.snapshot.Snapshot) or any mapping with the same arrays.

    adjust: the loop's own dispatch against EIA's, so EFP prices the generation the loop runs, not EIA's:
    {"fuel": {fuel: loop power-sector use / EIA's}, "price": {fuel: loop price / EIA's}, "gen": loop / EIA's
    generation}, each applied to every region's restart values (FUEL_OF, PRICE_OF). None: EIA's dispatch as is
    (the oracle's stand-in, operation for operation). Without it a scenario that adds load added sales to EFP
    but no fuel, so its generation price fell (dc50 2035: -8.2% on 9.9% more sales)."""
    r, y = irg - 1, iyr - 1
    a = lambda name: snap[name]  # noqa: E731
    fq = (adjust or {}).get("fuel", {})
    fp = (adjust or {}).get("price", {})
    fg = f32((adjust or {}).get("gen", 1.0))

    def fl(io, n):
        v = f32(a("UEFDOUT/" + n)[io - 1, r, y])
        if adjust is None:
            return v
        if n == "ugntlnr":
            return f32(v * fg)
        return f32(v * f32(fq.get(FUEL_OF.get(n), 1.0)))

    def pr(n):
        v = f32(a("UEFDOUT/" + n)[r, y])
        return v if adjust is None else f32(v * f32(fp.get(PRICE_OF.get(n), 1.0)))

    fuel, gen = {}, {}
    for io in (1, 2):
        v = f32(fl(io, "uflclnr") * pr("uprclnr"))
        v = f32(v + f32(f32(f32(fl(io, "uflgfnr") + fl(io, "uflginr")) + fl(io, "uflgcnr")) * pr("uprngnr")))
        v = f32(v + f32(fl(io, "ufldsnr") * pr("uprdsnr")))
        v = f32(v + f32(f32(fl(io, "uflrlnr") + fl(io, "uflrhnr")) * pr("uprrsnr")))
        v = f32(v + f32(fl(io, "uflwdnr") * pr("uprwdnr")))
        v = f32(v + f32(fl(io, "uflurnr") * PNUC))
        fuel[io] = v
        gen[io] = fl(io, "ugntlnr")
    out = {k: np.zeros(EFD_D_OWN, np.float32) for k in ("ertfl", "ertom", "ertso2", "ertnox", "erthg", "ertgsub")}
    out["ertomf"] = np.zeros((EFD_D_CAP, EFD_D_OWN), np.float32)
    out["ertomx"] = np.zeros((EFD_D_CAP, EFD_D_OWN), np.float32)
    gsum = max(f32(gen[1] + gen[2]), f32(1.0e-6))
    uptccst = pr("uptccst")
    for io in range(1, EFD_D_OWN + 1):
        sh, g, fu = OWNSHR[io - 1], gen[OWNSRC[io - 1]], fuel[OWNSRC[io - 1]]
        ertfl = f32(sh * fu)
        out["ertfl"][io - 1] = ertfl
        out["ertom"][io - 1] = f32(f32(sh * g) * VOM)
        out["ertomf"][0, io - 1] = f32(f32(sh * g) * FOM)
        out["ertso2"][io - 1] = f32(PALLW * ertfl)
        out["ertnox"][io - 1] = f32(PALLW * ertfl)
        out["erthg"][io - 1] = f32(f32(f32(0.1) * PALLW) * ertfl)
        out["ertgsub"][io - 1] = f32(f32(f32(sh * g) / gsum) * uptccst)
    erffl = np.zeros(EFD_D_NFL, np.float32)
    erffl[uiuf - 1] = f32(f32(fl(1, "uflurnr") + fl(2, "uflurnr")) * PNUC)
    out["erffl"] = erffl
    out["ewgfix"] = f32(f32(0.2) * out["ertfl"][2])
    out["ewgrev"] = f32(out["ertfl"][2] + out["ertom"][2])
    out["ewgrcc"] = f32(f32(0.01) * out["ewgrev"])
    out["ewgric"] = f32(f32(0.05) * out["ewgrev"])
    out["ewgrnw"] = f32(0.0)
    tt = lambda n: f32(a("UETTOUT/" + n)[r, y])  # noqa: E731
    k = f32(1000.0)
    for n in ("etdmmf", "etdmme", "etimpf", "etimpe", "etexpf", "etexpe"):
        out[n] = f32(tt("u" + n[1:]) * k)
    out["etdmdf"] = tt("utdmdf")
    out["etdmde"] = tt("utdmde")
    out["etimpd"] = f32(f32(f32(out["etimpf"] + out["etimpe"]) / f32(1.0e6)) * PTRADE)
    out["etexpd"] = f32(f32(f32(out["etexpf"] + out["etexpe"]) / f32(1.0e6)) * PTRADE)
    out["errps"] = pr("urpscstr")
    out["erdscar"] = f32(pr("utcar") * f32(a("EMISSION/emetax")[0, y]))
    mc = f64(f32(f32(fuel[1] + fuel[2]) / gsum))  # REAL*4 average, stored in REAL*8
    out["marcst"] = np.full((EFD_D_MSP, efd_d_mvs), mc)
    out["marcst2"] = np.full((EFD_D_MSP, efd_d_mvs), mc)
    out["etgen"] = f32(gen[1] + gen[2])
    return out
