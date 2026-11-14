"""NGMM's short-run gas supply curve, ported from natgas.ams (procedure SupplyCurveParameters).

The curve passes through HSM's expected production Q0 at last year's wellhead price P0. Six points,
each a (quantity, price) multiple of (Q0, P0), built outward from the centre:

    step3, step4: Q0 (1 -/+ per1),          P0 (1 -/+ per1 / elas3)      (centre, elasticity 0.5)
    step2, step5: step3/4 times (1 -/+ per2), prices times (1 - per2/elas2) or (1 + per2/elas4)
    step1:        step2 times (1 - elas1),   price 0                       (minimum production)
    step6:        step5 times (1 + maxq),    prices times (1 + maxq/elas5) (maximum production)

per = NGTDMREP/ngscrv_per (0.03, 0.09), elas = NGTDMREP/ngscrv_elas (0.8, 0.7, 0.5, 0.3, 0.2) and
maxq = 3, all as EIA writes them for option 2 (most supply states). Between points the price is linear
in quantity, as NGMM's stepped LP bounds make it.
"""
import numpy as np

PER = (0.03, 0.09)
ELAS = (0.8, 0.7, 0.5, 0.3, 0.2)
MAXQ = 3.0


def points(per=PER, elas=ELAS, maxq=MAXQ) -> tuple[np.ndarray, np.ndarray]:
    """Quantity and price multiples of (Q0, P0) at steps 1 to 6, both increasing."""
    p1, p2 = per
    e1, e2, e3, e4, e5 = elas
    q3, p3 = 1 - p1, 1 - p1 / e3
    q4, p4 = 1 + p1, 1 + p1 / e3
    q2, pp2 = q3 * (1 - p2), p3 * (1 - p2 / e2)
    q5, pp5 = q4 * (1 + p2), p4 * (1 + p2 / e4)
    q1, pp1 = q2 * (1 - e1), pp2 * (1 - e1 / e1)
    q6, pp6 = q5 * (1 + maxq), pp5 * (1 + maxq / e5)
    return np.array([q1, q2, q3, q4, q5, q6]), np.array([pp1, pp2, p3, p4, pp5, pp6])


Q_PTS, P_PTS = points()


def price(qratio):
    """P / P0 at production Q / Q0 (flat beyond the end points)."""
    return np.interp(qratio, Q_PTS, P_PTS)


def quantity(pratio):
    """Q / Q0 at price P / P0, the inverse of price()."""
    return np.interp(pratio, P_PTS, Q_PTS)
