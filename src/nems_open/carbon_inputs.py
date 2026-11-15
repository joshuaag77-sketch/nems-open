"""The carbon price in the units EIA's own models read it, for the models run inside the loop (coal AIMMS, LFMM GAMS).

NEMS's emissions policy module writes the carbon tax as EMISSION EMETAX(1, year) in 1987 $ per kg of carbon (EMM sets
it from ECP's price as ECP_PCAR * 0.001; LFMM turns it back into $ per metric ton CO2 as EMETAX * 1000 * 12/44), and
each fuel's carbon adder as EMABLK J<fuel>(year) = EMETAX(1, year) * EMEBLK E<fuel>(year), 1987 $ per MMBtu (EMEBLK in
kg C per MMBtu). The CMM reads EMETAX (COALEMM_PCACLNR, the carbon component it hands EMM); LFMM reads EMETAX for the
refinery's own emissions (CO2EmissionTax) and the J adders where it nets carbon out of product prices.
"""

import numpy as np

C_PER_CO2 = 12.0 / 44.0


def emetax_row(cp87_per_t_co2) -> np.ndarray:
    """EMETAX(1, year): 1987 $ per kg C from 1987 $ per metric ton CO2 (61,)."""
    return np.asarray(cp87_per_t_co2, dtype=np.float64) / C_PER_CO2 / 1000.0


def arrays(cp87_per_t_co2, base: dict) -> dict:
    """The arrays to override in a model's inputs: EMISSION/EMETAX row 1 and every EMABLK/J* whose EMEBLK/E* is in
    base. Keys keep base's spelling (upper or lower case). Empty when the price is zero in every year."""
    row = emetax_row(cp87_per_t_co2)
    if not np.any(row):
        return {}
    names = {k.upper(): k for k in base}
    out = {}
    if "EMISSION/EMETAX" in names:
        k = names["EMISSION/EMETAX"]
        e = np.array(base[k], dtype=np.float64)
        e[0, :] = row
        out[k] = e
    for up, k in names.items():
        if up.startswith("EMABLK/J"):
            factor = names.get("EMEBLK/E" + up[len("EMABLK/J"):])
            if factor is not None and np.shape(base[factor]) == np.shape(base[k]) == (61,):
                out[k] = row * np.asarray(base[factor], dtype=np.float64)
    return out
