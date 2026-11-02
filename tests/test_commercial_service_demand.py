"""COMServiceDemand port vs the oracle's internal state.

Feeds the port the oracle's state just before EIA's routine ran (sd_in) plus the
routine's own input tables (dumped at sd_out), and compares what the port computes
with the oracle's state just after (sd_out). Skipped until the oracle has run.
"""

import numpy as np
from oracle_harness import oracle_test

from nems_open.commercial.service_demand import NUM_DIV, service_demand
from nems_open.fortran_array import FArray

# The routine's private input tables, constant after the first call.
PRIVATE_INPUTS = ["existimprvht", "existimprvcl", "dcf", "marketpenetrationmels", "melselq",
                  "servicesindex", "xplicitmiscshr", "datactrservpenetration", "officepcpenetration",
                  "marketpenetrationsc", "pctscsavings", "ct_flag", "applyramp"]


def zeros(a):
    return FArray(np.zeros_like(a.a), a.lb)


def inputs(before, after, y):
    inp = dict(before)
    inp.update({k: after[k] for k in PRIVATE_INPUTS})
    for k in ("ssdnoshell", "nsdnoshell", "rsdnoshell", "totexplicitmiscelq"):
        inp[k] = zeros(after[k])
    return inp


def select(a, name, y):
    """The year EIA computed; EIA never rewrites the last division of ServDmdExBldg or regions past 10."""
    if name == "ShellHeatFactor":
        return a[:, :, 1, y]
    return a[:, :, slice(1, NUM_DIV) if name == "ServDmdExBldg" else slice(1, 11), y]


XDIST_BY_YEAR = True


oracle_test(globals(), tag="sd", port=service_demand, inputs=inputs, select=select, outputs=[
    "ServDmdExBldg", "NewServDmd", "ServDmdSurv", "RetireServDmd", "ShellHeatFactor"])
