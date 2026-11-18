"""AIMMS poll timeouts count awake time only: a laptop sleep must not fail a solve (dc50, 2026-11-18)."""

from nems_open.ngmm import aimms


def test_sleep_gap_is_not_counted(monkeypatch):
    clock = iter([0.0, 1.0, 2.0, 2.0 + 9 * 3600, 3.0 + 9 * 3600])
    monkeypatch.setattr(aimms.time, "time", lambda: next(clock))
    a = aimms.AwakeTimer(gap=30)
    assert a() == 1.0 and a() == 2.0
    assert a() == 2.0          # nine-hour gap: asleep
    assert a() == 3.0
