"""AVRPRC (uefp.f): one component's books and prices for one region.

Called by GENERA ('G'), TRANSM ('T') and DISTRI ('D'). On a year's first
iteration it first rolls the capital accounts forward (construction work in
progress, decommissioning fund, phase-ins, sale/leasebacks, tax credits, book
and tax depreciation); every iteration it then sets expenses, interest,
revenue requirement and rates, and on EFP's final pass writes the statements.
"""

from nems_open.emm.efp.common import i
from nems_open.emm.efp.cwip import eladcr, elcwip
from nems_open.emm.efp.depreciation import elbkdp, elitc, eltsaf, eltxdp
from nems_open.emm.efp.expenses import elinex, elrevs, elxpns
from nems_open.emm.efp.phasein import elnd, elphin, elsl
from nems_open.emm.efp.rates import elrate
from nems_open.emm.efp.statements import stmts


def avrprc(s, nrgn, icall):
    if i(s, "curitr") == 1 and i(s, "efpitr") == 1:
        eladcr(s)
        elcwip(s, nrgn, icall)
        elnd(s, nrgn, 6, icall)
        elphin(s, nrgn)
        elsl(s, nrgn)
        elitc(s)
        elbkdp(s, nrgn, icall)
        eltxdp(s, nrgn, icall)
        eltsaf(s)
    elxpns(s, nrgn, icall)
    elinex(s, nrgn)
    elrevs(s, icall, nrgn)
    elrate(s, icall, nrgn)
    if i(s, "efpfcrl") == 1:
        stmts(s, nrgn, icall)
