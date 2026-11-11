"""CONTAB port vs the industrial oracle: report-writer consumption tables.

Each tag is one CONTAB call (region 1-4, or the national call 5) for one industry; the
port runs on the state before the call and is compared with the state after it.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.contab import ALL_TABLES, contab

YEARS = [36, 37, 38, 41, 51, 61]
TAGS = [("con", 4), ("con4", 4), ("con2", 4), ("con3", 4), ("con6", 4), ("con7", 4), ("con9", 4), ("con24", 4),
        ("cons", 5), ("cons7", 5), ("cons24", 5)]
NEED = ["inddir", "indreg", "indnum", "iyr", "mainfuels", "qtymain", "qtyrenw", "qtybyind", "qelrf", "qeleth", "qngrf",
        "qngeth", "qclrf", "qcleth", "qrlrf", "qdsrf", "qlgrf", "qsgrf", "qpcrf", "qccrf", "qotrf", "qh2rf",
        "qelhm", "qnghmhp", "qnghmpf", "cgogsq"] + ALL_TABLES

pytestmark = pytest.mark.skipif(not oracle_state.available("con_out", 61, "ind"), reason="oracle state not dumped")


def rel_err(a, b):
    a, b = np.asarray(getattr(a, "a", a), dtype=np.float64), np.asarray(getattr(b, "a", b), dtype=np.float64)
    return float((np.abs(a - b) / np.maximum(np.abs(b), 1e-3)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag,icr", TAGS)
def test_contab(tag, icr, y):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip("not dumped")
    before = oracle_state.load(f"{tag}_in", y, "ind", only=NEED)
    after = oracle_state.load(f"{tag}_out", y, "ind", only=NEED)
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
    contab(s, icr if icr == 5 else int(s["indreg"]))
    for name in ALL_TABLES + ["qtybyind"]:
        assert rel_err(s[name], after[name]) < 1e-5, name
