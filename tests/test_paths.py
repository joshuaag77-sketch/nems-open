"""Finding EIA's upstream checkout from a fresh git worktree."""

import importlib

from nems_open import paths


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("NEMS_UPSTREAM", str(tmp_path))
    assert paths._find_upstream() == tmp_path


def test_finds_the_main_checkout_without_the_env_var(monkeypatch):
    """A fresh worktree has no nems-upstream/ (it is git-ignored); the search must still land on the one in
    the main checkout, or a sibling checkout, when any exists."""
    monkeypatch.delenv("NEMS_UPSTREAM", raising=False)
    found = paths._find_upstream()
    assert found.name == "nems-upstream"
    importlib.reload(paths)
