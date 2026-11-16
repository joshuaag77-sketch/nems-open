import subprocess

from nems_open.lfmm import gams_io


def _setup(monkeypatch, fail_win):
    calls = []

    def run(args, check, env=None):
        calls.append(args[0])
        if args[0] != "wsl" and len(calls) <= fail_win:
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(gams_io, "use_wsl", lambda: False)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return calls


def test_blocked_dll_load_retries_on_windows(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, fail_win=1)
    gams_io.helper("read", tmp_path / "a.gdx", tmp_path / "o.pkl")
    assert len(calls) == 2 and "wsl" not in calls


def test_blocked_every_time_falls_back_to_wsl(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, fail_win=3)
    gams_io.helper("read", tmp_path / "a.gdx", tmp_path / "o.pkl")
    assert calls[-1] == "wsl" and len(calls) == 4
