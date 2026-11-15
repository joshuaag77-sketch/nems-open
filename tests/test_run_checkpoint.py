import pickle

import numpy as np
import pytest

from nems_open import run_model

ARGS = dict(start_year=2027, end_year=2029, ported=(), cycles=2, maxitr=4)


def test_resume_from_checkpoint_matches_full_run(tmp_path, monkeypatch):
    full = run_model.run(**ARGS)
    path = tmp_path / "x.pkl"
    saved = {}
    real = run_model._save_checkpoint

    def save(p, tag, state):
        real(p, tag, state)
        saved["cycle"] = state["cycle"]
        raise KeyboardInterrupt   # crash right after cycle 1 is saved
    monkeypatch.setattr(run_model, "_save_checkpoint", save)
    with pytest.raises(KeyboardInterrupt):
        run_model.run(**ARGS, checkpoint=(path, "t"))
    monkeypatch.setattr(run_model, "_save_checkpoint", real)
    assert saved["cycle"] == 1 and path.exists()
    resumed = run_model.run(**ARGS, checkpoint=(path, "t"))
    for k in ("MPBLK/pmgtr", "MPBLK/pelin"):
        assert np.allclose(resumed.prices[k], full.prices[k], equal_nan=True)
    assert np.allclose(resumed.quantities["QBLK/qngin"], full.quantities["QBLK/qngin"], equal_nan=True)
    assert len(resumed.passes) == len(full.passes)


def test_other_tag_is_ignored(tmp_path):
    path = tmp_path / "x.pkl"
    run_model._save_checkpoint(path, "a", {"cycle": 1})
    assert run_model._load_checkpoint(path, "b") is None
    assert run_model._load_checkpoint(path, "a")["cycle"] == 1
