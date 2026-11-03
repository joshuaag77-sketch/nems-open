"""EFP expenses, interest expense and revenue requirement: ELXPNS, ELINEX, ELREVS (uefp.f).

All variables here are REAL*4 (or INTEGER), so every operation is float32 and the
expressions keep the Fortran's left-to-right order. NumPy float32 scalars keep the
type through + - * /; Fortran's REAL constants are written f32(...).
"""

import numpy as np

from nems_open.emm.efp.common import f32, i, put


def elxpns(s, nrgn, icall):
    """Nominal fuel, nuclear fuel stock and O&M by ownership (1 private, 2 public) and
    working capital. nrgn and icall are not used by the Fortran."""
    gdp = s["mc_jpgdp"][i(s, "curiyr")]
    shr, tfl, tom, nfs, wc = s["estshr"], s["ertfln"], s["ertomn"], s["ernfsn"], s["erwc"]
    for k in (1, 2):
        tfl[k] = f32(0.0)
        tom[k] = f32(0.0)
        if shr[k] != 0.0:
            tfl[k] = s["efpfl"] + s["blksum"]
            tfl[k] = tfl[k] * shr[k] * gdp
            nfs[k] = f32(3.5) * s["efpnuc"] * shr[k] * gdp
            tom[k] = (s["efpom"] * shr[k]) * gdp
            wc[k] = f32(0.125) * (tom[k] + tfl[k])
    # quirk kept: ERNFSN and ERWC keep their old value for an ownership with zero share
    put(s, "blksum", s["blksum"] * gdp)
    for k in range(1, 5):
        s["ppwrblk"][k] = s["ppwrblk"][k] * gdp


def elinex(s, nrgn):
    """Interest expense, preferred dividends and average common equity."""
    g = {n: s[n] for n in (
        "estshr", "eramd", "ertup", "erbcwp", "erwc", "erabde", "erprdf", "erditc", "ernfsn", "edisnt",
        "epidef", "eslndg", "erbond", "esprlt", "erob", "erobl", "erbndl", "erbde", "esemdt", "esemdl",
        "esemdb", "esrtlt", "erpref", "esprps", "erpf", "erpflps", "esemps", "esempl", "erprfl", "esempb",
        "esrtps", "erliex", "eramdl", "elprlt", "eslprc", "ersiex", "esrtst", "esprst", "elprst", "ertiex",
        "erpsdv", "elprps", "eravce", "esprce", "elprce")}
    fullyr = int(s["usyear"][i(s, "curiyr")])
    zero, two = f32(0.0), f32(2.0)
    for k in (1, 2):
        if g["estshr"][k] == 0.0:
            continue
        amd, bond = g["eramd"], g["erbond"]
        amd[k] = (((((((g["ertup"][k] + g["erbcwp"][k]) + g["erwc"][k]) - g["erabde"][k]) - g["erprdf"][k])
                    - g["erditc"][k]) + g["ernfsn"][k]) - g["edisnt"][k]) + g["epidef"][k] - g["eslndg"][k]
        bond[k] = zero
        if amd[k] != 0.0:
            bond[k] = amd[k] * g["esprlt"][k]
            if fullyr == i(s, "uestyr"):
                if bond[k] < g["erob"][k]:
                    g["erob"][k] = bond[k]
                    g["erobl"][k] = bond[k]
                    g["erbndl"][k] = bond[k]
            retire = g["esprlt"][k] * g["erbde"][k]
            g["erob"][k] = g["erobl"][k] - retire
            if g["erob"][k] <= 0.0:
                retire = retire + g["erob"][k]
                g["erob"][k] = zero
            if bond[k] == 0.0:
                g["esemdt"][k] = zero
            if bond[k] > 0.0:
                g["esemdt"][k] = (g["esemdl"][k] * g["erbndl"][k] - g["esemdb"][k] * retire
                                  + g["esrtlt"][k] * (bond[k] - g["erbndl"][k] + retire)) / bond[k]
        # preferred stock
        g["erpref"][k] = zero
        if amd[k] != 0.0:
            g["erpref"][k] = amd[k] * g["esprps"][k]
            retire = g["esprps"][k] * g["erbde"][k]
            g["erpf"][k] = g["erpflps"][k] - retire
            if g["erpf"][k] <= 0.0:
                retire = retire + g["erpf"][k]
                g["erpf"][k] = zero
            if g["erpref"][k] == 0.0:
                g["esemps"][k] = zero
            if g["erpref"][k] != 0.0:
                g["esemps"][k] = (g["esempl"][k] * g["erprfl"][k] - g["esempb"][k] * retire
                                  + g["esrtps"][k] * (g["erpref"][k] - g["erprfl"][k] + retire)) / g["erpref"][k]
        g["erliex"][k] = g["esemdt"][k] * (amd[k] * g["esprlt"][k] + g["eramdl"][k] * g["elprlt"][k]
                                           - g["eslprc"][k] * g["esprlt"][k]) / two
        g["ersiex"][k] = g["esrtst"][k] * (amd[k] * g["esprst"][k] + g["eramdl"][k] * g["elprst"][k]
                                           - g["eslprc"][k] * g["esprst"][k]) / two
        g["ertiex"][k] = g["erliex"][k] + g["ersiex"][k]
        g["erpsdv"][k] = g["esemps"][k] * (amd[k] * g["esprps"][k] + g["eramdl"][k] * g["elprps"][k]
                                           - g["eslprc"][k] * g["esprps"][k]) / two
        g["eravce"][k] = (amd[k] * g["esprce"][k] + g["eramdl"][k] * g["elprce"][k]
                          - g["eslprc"][k] * g["esprce"][k]) / two


def elrevs(s, icall, nrgn):
    """Rate base, rate of return, revenue requirement and (lagged) revenues."""
    one, neg1, two = f32(1.0), f32(-1.0), f32(2.0)
    v = {n: s[n] for n in (
        "estshr", "errvlg", "errb", "ertup", "errcwp", "erwc", "erabde", "erprdf", "ernfsn", "ercnbv",
        "ercnad", "eslndg", "esftxr", "erditc", "opitcrb", "opavrb", "errbrr", "erafdl", "errbl", "erdlrb",
        "edisnt", "esrr", "esprlt", "esemdt", "esprst", "esrtst", "esprce", "esrtce", "esprps", "esemps",
        "errvrq", "ertfln", "ertomn", "erndfpmt", "erbde", "eraitc", "erfitc", "erafdc", "erffdc", "eroffs",
        "eredtf", "epind", "esllp", "eslagn", "erprtx", "ersltx", "ertdwo", "ertiex", "esstxr", "ertdrg",
        "ercidc", "egtxrt", "eilag", "eravce", "eserce", "erpsdv", "edisyr", "epiret", "erfdc", "eratsf",
        "elrbrr", "elrcwp", "eltomn", "eltfln", "elbde", "elaitc", "elfitc", "elafdc", "elffdc",
        "eloffs", "elllp", "ellagn", "elprtx", "elsltx", "eltdwo", "eltiex", "elcidc", "eqtlsl", "eltlsl")}
    curiyr = i(s, "curiyr")
    fullyr = int(s["usyear"][curiyr])
    # ELRB and ELRVRQ are SAVEd locals; each is set before it is read within one ownership pass
    elrb = np.zeros(3, dtype=np.float32)
    elrvrq = np.zeros(3, dtype=np.float32)
    with np.errstate(all="ignore"):
        for k in (1, 2):
            V = {n: a[k] for n, a in v.items()}
            v["errvlg"][k] = f32(0.0)
            if V["estshr"] != 0.0:
                rb = (V["ertup"] + V["errcwp"] + V["erwc"] - V["erabde"] - V["erprdf"] + V["ernfsn"]
                      - (V["ercnbv"] - V["ercnad"]) - V["eslndg"])
                if v["opitcrb"][k] == 2 and V["esftxr"] != 0.0:
                    rb = rb - V["erditc"]
                v["errb"][k] = rb
                if v["opavrb"][k] == 2 or curiyr + i(s, "uhbsyr") <= i(s, "efpsyr"):
                    rbrr = rb - V["erafdl"]
                else:
                    rblast = V["errbl"]
                    if fullyr == i(s, "uestyr"):
                        rblast = rblast + V["erwc"] + V["ernfsn"]
                    rbrr = (rblast + V["erdlrb"] + rb) / two
                rbrr = rbrr - V["edisnt"]
                v["errbrr"][k] = rbrr
                esrr = (V["esprlt"] * V["esemdt"] + V["esprst"] * V["esrtst"] + V["esprce"] * V["esrtce"]
                        + V["esprps"] * V["esemps"])
                if icall in ("T", "D"):
                    esrr = esrr - s["roradj"]
                v["esrr"][k] = esrr
                if icall == "G" and k == 1:
                    s["sv_prgen_esrr"][curiyr, nrgn] = esrr
                ftx, stx, gtx = V["esftxr"], V["esstxr"], V["egtxrt"]
                den = one - gtx - stx - ftx + gtx * ftx + stx * ftx
                tfl, tom, nd = V["ertfln"], V["ertomn"], V["erndfpmt"]
                rrq = (rbrr * esrr + tfl + tom + nd + V["erbde"] - V["eraitc"] - V["erfitc"]
                       - V["erafdc"] - V["erffdc"] - V["eroffs"] - V["eredtf"] - V["epind"] + V["esllp"]
                       - V["eslagn"] + (V["erprtx"] + V["ersltx"]) * (one - ftx)
                       + (tfl + tom + V["ertdwo"] + V["ertiex"] + V["esllp"] + nd) * ((neg1 * stx) + stx * ftx)
                       + (tfl + tom + V["ertdrg"] + nd + (V["ertiex"] - V["ercidc"]) + V["esllp"])
                       * (neg1 * ftx)) / den
                v["errvrq"][k] = rrq
                lag = int(V["eilag"])  # REAL to INTEGER truncates
                if lag == -1:
                    v["errvlg"][k] = (V["eravce"] * V["eserce"] + V["erpsdv"] + V["edisyr"] - V["epind"]
                                      - V["epiret"] - V["erfdc"] + V["ertiex"] + tfl + tom + V["erbde"]
                                      - V["eraitc"] + nd - V["erfitc"] - V["erafdc"] - V["erffdc"]
                                      - V["eratsf"] - V["eredtf"] + V["esllp"] - V["eslagn"]
                                      + (V["erprtx"] + V["ersltx"]) * (one - ftx)
                                      + (tfl + tom + V["ertdwo"] + V["ertiex"] + nd + V["esllp"])
                                      * ((neg1 * stx) + stx * ftx)
                                      + (tfl + tom + V["ertdwo"] + (V["ertiex"] - V["ercidc"]) + V["esllp"] + nd)
                                      * (neg1 * ftx)) / den
                elif lag > 1:
                    elrb[k] = V["elrbrr"] + (V["errcwp"] - V["elrcwp"])
                    ltom, ltfl = V["eltomn"], V["eltfln"]
                    elrvrq[k] = ((elrb[k] * esrr + ltom + ltfl + nd + V["elbde"] - V["elaitc"] - V["elfitc"]
                                  - V["elafdc"] - V["elffdc"] - V["eloffs"] - V["eredtf"] - V["epind"]
                                  + V["elllp"] - V["ellagn"] + (V["elprtx"] + V["elsltx"]) * (one - ftx)
                                  + (ltom + ltfl + V["eltdwo"] + V["eltiex"] + V["elllp"] + nd)
                                  * ((neg1 * stx) + stx * ftx)
                                  + (ltom + ltfl + V["ertdrg"] + nd + (V["eltiex"] - V["elcidc"]) + V["elllp"])
                                  * (neg1 * ftx)) * V["eqtlsl"] / V["eltlsl"]) / den
                    if lag == 3:
                        v["errvlg"][k] = (f32(0.5) * elrvrq[k]) + (f32(0.5) * rrq)
                    elif lag == 4:
                        v["errvlg"][k] = (f32(0.75) * elrvrq[k]) + (f32(0.25) * rrq)
                    elif lag == 5:
                        v["errvlg"][k] = elrvrq[k]
                    else:
                        v["errvlg"][k] = (f32(0.25) * elrvrq[k]) + (f32(0.75) * rrq)
                else:
                    v["errvlg"][k] = rrq
            # quirk kept: the T and D scaling applies even when the ownership share is zero
            if icall == "T":
                v["errvlg"][k] = v["errvlg"][k] * s["omadjtr"][curiyr]
            elif icall == "D":
                v["errvlg"][k] = v["errvlg"][k] * s["omadjds"][curiyr]
