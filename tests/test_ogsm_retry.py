"""HSM worker failures retry before failing the run (dc50, 2026-11-18: silent worker death)."""
import types

import numpy as np
import pytest

from nems_open.ogsm import couple


def _fake_run(results):
    def run(cmd, **kw):
        rc = next(results)
        if rc == 0:
            np.savez(cmd[-1], ogenagprd=np.ones(3))
        return types.SimpleNamespace(returncode=rc, stderr="", stdout="")
    return run


def test_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(couple, "work_dir", lambda: tmp_path / "w")
    monkeypatch.setattr(couple.subprocess, "run", _fake_run(iter([3, 0])))
    out = couple.production(scedes="retry-test.csv")
    assert "ogenagprd" in out


def test_gives_up_with_rc(tmp_path, monkeypatch):
    monkeypatch.setattr(couple, "work_dir", lambda: tmp_path / "w")
    monkeypatch.setattr(couple.subprocess, "run", _fake_run(iter([3, 3, 3])))
    with pytest.raises(RuntimeError, match="rc 3"):
        couple.production(scedes="retry-test2.csv")
