"""TMAC (tran.f): macroeconomic drivers for the light-duty model.

Fuel tax in 1987 dollars, highway diesel price, IRA vehicle and battery credits,
income per capita, population by age group and sex, licensing rates projected
from employment, and licensed drivers by region.

`s` is the state dict from the oracle dump (lowercase Fortran names, FArrays with
Fortran bounds). The routine updates it in place, as the Fortran updates its
module and COMMON variables.
"""

from nems_open.transportation.common import AGEGRP, MNUMCR, f32, fsum


def tmac(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["yrs"])
    jp = s["mc_jpgdp"]

    s["fueltax87"][n] = s["fueltax"][n] / jp[n]
    s["hwypdstr"][1:MNUMCR, n] = s["pdstrhwy"][1:MNUMCR, n]

    s["ira_veh_cred"] = f32(0.0)
    s["ira_bat_cred"] = f32(0.0)
    if s["ira_stim"] == 1.0:
        s["ira_veh_cred"] = f32(3750.0) / jp[n] * jp[1]
        s["ira_bat_cred"] = f32(3750.0) / jp[n] * jp[1]

    ypdr, np_, np16 = s["mc_ypdr"], s["mc_np"], s["mc_np16a"]
    defl = jp[23] / jp[11]
    s["inc00_d_np"][1:MNUMCR, n] = (ypdr[1:MNUMCR, n] / np_[1:MNUMCR, n]) * f32(1000.0) / defl
    s["inc00_d_16"][1:MNUMCR, n] = (ypdr[1:MNUMCR, n] / np16[1:MNUMCR, n]) * f32(1000.0) / defl
    s["inc90_d_np"][1:MNUMCR, yrs] = (ypdr[1:MNUMCR, n] / np_[1:MNUMCR, n]) * jp[1] * f32(1000.0)
    s["inc_gr_regn"][1:MNUMCR, yrs] = s["inc90_d_np"][1:MNUMCR, yrs] / s["inc90_d_np"][1:MNUMCR, yrs - 1]

    # Population by age group and sex. The macro case picks the age distribution.
    suffix = {4: "_l", 5: "_h"}.get(int(s["mmac"]), "")
    m_dist, f_dist = s["m_cd_age_dist" + suffix], s["f_cd_age_dist" + suffix]
    np15 = s["tmc_np15a"]
    for iagr in range(1, AGEGRP + 1):
        np15[iagr, 1, 1:MNUMCR - 2, n] = np16[1:MNUMCR - 2, n] * m_dist[iagr, n, 1:MNUMCR - 2]
        np15[iagr, 2, 1:MNUMCR - 2, n] = np16[1:MNUMCR - 2, n] * f_dist[iagr, n, 1:MNUMCR - 2]
    s["iagr"] = AGEGRP + 1  # DO-loop variable after the loop

    # Licensing rates move with the employment rate after the last history year.
    emp = s["emp_rate_ld"]
    emp[n] = s["mc_eea"][n] / np16[11, n]
    emp_gr = (emp[n] / emp[n - 1]) - f32(1.0)
    if int(s["curcalyr"]) > int(s["licrhistyr"]):
        elas_t = s["lic_elas"][1:MNUMCR - 2, 1:AGEGRP].T
        for key, sex in (("licrate_m", 1), ("licrate_f", 2)):
            lr = s[key]
            lr[1:AGEGRP, n, 1:MNUMCR - 2] = (lr[1:AGEGRP, n - 1, 1:MNUMCR - 2]
                                             + s["lic_trend"][1:AGEGRP, sex, 1:MNUMCR - 2] + elas_t * emp_gr)
            lr[1:AGEGRP, n, 1:MNUMCR - 2] = (
                lr[1:AGEGRP, n, 1:MNUMCR - 2].clip(max=s["lic_max"][1:AGEGRP, sex, 1:MNUMCR - 2]))

    ld = s["licdriver"]
    ld[1:AGEGRP, 1, 1:MNUMCR - 2, n] = np15[1:AGEGRP, 1, 1:MNUMCR - 2, n] * s["licrate_m"][1:AGEGRP, n, 1:MNUMCR - 2]
    ld[1:AGEGRP, 2, 1:MNUMCR - 2, n] = np15[1:AGEGRP, 2, 1:MNUMCR - 2, n] * s["licrate_f"][1:AGEGRP, n, 1:MNUMCR - 2]
    ld[1:AGEGRP, 1:2, 11, n] = fsum(ld[1:AGEGRP, 1:2, 1:MNUMCR - 2, n], axis=2)
