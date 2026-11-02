"""COMConsumption port vs the oracle's internal state.

Feeds the port the state just before EIA's routine ran (cn_in), plus inputs only
the routine sees (on-site generation outputs, minor-fuel tables, switches: from
cn_out) and the arrays it shares with technology choice (tc_out), and compares
what it writes with cn_out. Skipped until the oracle has run.
"""

from oracle_harness import oracle_test

from nems_open import oracle_state
from nems_open.commercial.consumption import consumption

FROM_CN_OUT = ["trills", "trillsownuse", "shbtu", "hwbtu", "fuelusage", "flooradj", "defaultprices",
               "ifueltype", "ntek", "steodat", "flagregsteo", "ef1", "ef2", "ef3", "nrgbill",
               "prsvstdsavings", "foodsvchlthldgfloortot", "unbenchedcon", "cmfinalunbenchuse",
               "solarpvcontrib", "minfuelalpha", "minfuelbeta"]
FROM_TC_OUT = ["sdbyfuel", "equipsd"]


def inputs(before, after, y):
    tc = oracle_state.load("tc_out", y)
    inp = dict(before)
    inp.update({k: after[k] for k in FROM_CN_OUT})
    inp.update({k: tc[k] for k in FROM_TC_OUT})
    return inp


XDIST_BY_YEAR = True


oracle_test(globals(), tag="cn", port=consumption, inputs=inputs, outputs=[
    "enduseconsump", "euconwithdg", "cmeffind", "finalendusecon", "unbenchedcon", "cmfinalenduse",
    "cmfinalunbenchuse", "cmusconsumption", "cmusavgeff", "distservconsump", "distservsteam",
    "cmusdistserv", "cmfinalendusecon", "solarpvcontrib", "solarrenewablecontrib", "cmseds"])
