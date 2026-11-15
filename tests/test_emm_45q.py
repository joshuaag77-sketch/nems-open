"""45Q lasts 12 years from the year a unit starts capturing, for starts from 2017 to 2038 (udat.f UL_45Q_YR, EC_45Q)."""

import numpy as np

from nems_open.emm import dispatch
from nems_open.emm.regions import NUM_EMM

RULE = (2017, 2038, 12)


def _history(adds: dict, last: int) -> dict:
    """Year-end capacity of both capture groups from {year: GW added in region 1}."""
    out, total = {}, 0.0
    for t in range(RULE[0] - 1, last + 1):
        total += adds.get(t, 0.0)
        cap = np.zeros(NUM_EMM)
        cap[0] = total
        out[t] = {g: cap.copy() for g in dispatch.CAPTURE_GROUPS}
    return out


def test_credit_ends_twelve_years_after_start():
    h = _history({2030: 4.0, 2032: 12.0}, 2045)
    share = lambda y: dispatch.credit_share(h, y, RULE)["coal_ccs"][0]
    assert share(2041) == 1.0
    assert np.isclose(share(2042), 12.0 / 16.0)     # the 2030 cohort's 12 years are 2030-2041
    assert share(2044) == 0.0


def test_no_credit_for_starts_after_last_year():
    h = _history({2040: 5.0}, 2041)
    assert dispatch.credit_share(h, 2041, RULE)["gas_ccs"][0] == 0.0


def test_empty_region_has_zero_share():
    h = _history({}, 2035)
    assert dispatch.credit_share(h, 2035, RULE)["coal_ccs"][1] == 0.0
