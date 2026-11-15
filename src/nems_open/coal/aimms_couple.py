"""EIA's real coal model (coal.ams, AIMMS) as run_model's coal market: run(coal="aimms").

How NEMS runs the CMM: the AIMMS library stays open; each iteration NEMS writes coal/toAIMMS/GlobalDataToAIMMS_<year>_<itr>.txt
(everything in coalputvars.txt) and the library solves and writes coal/fromAIMMS/GlobalDataToNEMS_<year>_<itr>.txt. The
model carries its lag state (prior production, prices, targets) from call to call.

Here: one AIMMS process for a whole run (coal/aimms_run.py's wrapper, procedure serve_coal, which waits for
coal/serve.txt). Each loop iteration run_model calls begin(year, itr, q, prices, fcrl) with the demand the loop just
settled. The input file is cb2026's restart with the loop's coal use (QBLK qcl*, qmcin; the power sector's coal by coal
region and plant type, COALEMM QCLCLNR, and EMM's unit-level burn scaled to the loop's qclel) and the fuel prices the
CMM reads (MPBLK pelin, pdsin, pdstr, prltr, prhtr, and last iteration's coal prices). prices() then hands back the
CMM's delivered coal prices (MPBLK pclel, pclin, pclrs, pclcm, pclsn, pmcin). Years 2024 (the CMM's base year) to
start_year - 1 run first on cb2026's own inputs.

calibrate: the CMM run once per iteration on cb2026's final inputs lands a little off EIA's restart (the restart is the
end of several iterations and five cycles). With calibrate each price is multiplied by EIA's value over the CMM's own on
cb2026's inputs (reference.pkl, built on first use by `python -m nems_open.coal.aimms_couple`), so the baseline is EIA's
and a run's moves are the CMM's.

Not passed: the carbon tax the CMM reads (EMISSION EMETAX) stays cb2026's (zero); the loop's carbon price reaches coal
prices through the supply stand-in's carbon adders, and coal demand through power-sector switching.
"""

import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from nems_open.coal import aimms_run
from nems_open.ngmm.aimms import parse_composite, to_array
from nems_open.snapshot import Snapshot

RUN_DIR = Path(os.environ.get("NEMS_COAL_RUN", Path.home() / "dev" / "oracle-cache" / "coal-aimms"))
FIRST = aimms_run.BASE_YEAR          # 2024
# Every CMM solve appends one line here (a log for a later write-up; it never feeds back into results).
SHOWREEL = Path(os.environ.get("NEMS_SHOWREEL", Path.home() / "dev" / "aimms-showreel"))
SAMPLE_YEAR = 2030
BASINS = ("Northern Appalachia", "Central Appalachia", "Interior", "Lignite", "Powder River", "Other West")


def solve_info(path: Path) -> dict:
    """The math program's own report from File_Call (solve_info.txt): rows, columns, nonzeros, objective,
    iterations, solution time, status, solver."""
    out = {}
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for m in re.finditer(r"(?:\w+::)?info_(\w+)\s*:=\s*([^;]+);", text):
        v = m.group(2).strip().strip("'\"")
        try:
            out[m.group(1)] = float(v)
        except ValueError:
            out[m.group(1)] = v
    return out


def headline(o: dict, year: int) -> dict:
    """A few outputs worth a sentence: production by basin (Mt), Powder River share, delivered coal prices (1987$/MMBtu)."""
    j = year - 1990
    h = {}
    if "COALREP_COALPROD2" in o:
        prod = to_array(o["COALREP_COALPROD2"], (11, 17, 61))[10, :6, j]
        h["production_mt"] = {b: round(float(v), 2) for b, v in zip(BASINS, prod)}
        h["powder_river_share"] = round(float(prod[4] / prod.sum()), 4) if prod.sum() > 0 else None
    for k, label in (("MPBLK_PCLEL", "price_power"), ("MPBLK_PCLIN", "price_industry"), ("MPBLK_PMCIN", "price_coking")):
        if k in o:
            h[label] = round(float(to_array(o[k], (11, 61))[10, j]), 4)
    return h
PRICE_OUT = ("MPBLK/pclel", "MPBLK/pclin", "MPBLK/pclrs", "MPBLK/pclcm", "MPBLK/pclsn", "MPBLK/pmcin")
Q_IN = ("QBLK/QCLEL", "QBLK/QCLRS", "QBLK/QCLCM", "QBLK/QCLIN", "QBLK/QCLRF", "QBLK/QCLSN", "QBLK/QMCIN")
P_IN = ("MPBLK/PELIN", "MPBLK/PDSIN", "MPBLK/PDSTR", "MPBLK/PRLTR", "MPBLK/PRHTR",
        "MPBLK/PCLRS", "MPBLK/PCLCM", "MPBLK/PCLIN", "MPBLK/PCLSN", "MPBLK/PCLEL")


def _loop_key(key: str) -> str:
    """"QBLK/QCLEL" -> "QBLK/qclel", the loop's naming."""
    b, v = key.split("/")
    return f"{b}/{v.lower()}"


class CoalProcess:
    """One AIMMS process serving CMM calls (single process: RAM is the limit on this machine)."""

    def __init__(self, run: Path = RUN_DIR, fresh: bool = True, timeout: float = 900, source: str = "",
                 showreel: bool = True):
        self.run = Path(run)
        if fresh or not (self.run / "coal").exists():
            aimms_run.prepare(self.run)
        self.coal = self.run / "coal"
        (self.coal / "export.on").unlink(missing_ok=True)
        for f in ("serve.txt", "done.txt"):
            (self.coal / f).unlink(missing_ok=True)
        self.timeout = timeout
        self.snap = Snapshot()
        self.source, self.showreel, self.cycle = source, showreel, None
        log = open(self.run / "aimms_stdout.txt", "w")
        w = self.run / "main" / "wrapper"
        self.proc = subprocess.Popen([str(aimms_run.AIMMS), "-Rserve_coal", str(w / "wrapper.aimms"), "--hidden"],
                                     cwd=w, stdout=log, stderr=subprocess.STDOUT)

    def _request(self, text: str):
        tmp = self.coal / "serve.tmp"
        tmp.write_text(text)
        os.replace(tmp, self.coal / "serve.txt")

    def call(self, year: int, itr: int, arrays: dict | None = None, fcrl: int = 0) -> tuple[dict, float]:
        """Write the inputs, run the CMM for (year, itr), return its outputs ({"MPBLK_PCLEL": {(r, globalyr): v}})."""
        aimms_run.write_input(year, itr, self.coal / "toAIMMS", self.snap, arrays, fcrl)
        done, err = self.coal / "done.txt", self.coal / "log" / "aimmsRunOnly.err"
        done.unlink(missing_ok=True)
        err.unlink(missing_ok=True)
        t = time.time()
        self._request(f"req_year := {year} ;\nreq_itr := {itr} ;\nreq_quit := 0 ;\n")
        while not done.exists():
            if self.proc.poll() is not None:
                raise RuntimeError(f"AIMMS exited ({self.proc.returncode}) during the CMM {year} itr {itr}; see {self.run}")
            if time.time() - t > self.timeout:
                raise TimeoutError(f"CMM {year} itr {itr} took over {self.timeout} s")
            time.sleep(0.1)
        if err.exists() and err.read_text(errors="replace").strip():
            raise RuntimeError(f"CMM {year} itr {itr}: {err.read_text(errors='replace').strip()[:300]}")
        sec = time.time() - t
        out_file = self.coal / "fromAIMMS" / f"GlobalDataToNEMS_{year}_{itr:02d}.txt"
        out = parse_composite(out_file)
        if self.showreel:
            self._log(year, itr, fcrl, sec, out, out_file)
        return out, sec

    def _log(self, year, itr, fcrl, sec, out, out_file):
        """One JSON line per solve in SHOWREEL/coal.jsonl, and the sample year's input and output files."""
        try:
            SHOWREEL.mkdir(parents=True, exist_ok=True)
            info = solve_info(self.coal / "solve_info.txt")
            line = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": "coal (EIA CMM, coal.ams)",
                    "source": self.source, "year": year, "cycle": self.cycle, "iteration": itr, "fcrl": fcrl,
                    "rows": info.get("rows"), "columns": info.get("columns"), "nonzeros": info.get("nonzeros"),
                    "solver": info.get("solver"), "status": info.get("status"), "objective": info.get("objective"),
                    "simplex_iterations": info.get("iterations"), "solver_time_s": info.get("solution_time"),
                    "call_time_s": round(sec, 3), "headline": headline(out, year)}
            with open(SHOWREEL / "coal.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
            sample = SHOWREEL / f"coal_sample_{SAMPLE_YEAR}"
            if year == SAMPLE_YEAR and itr == 1 and not sample.exists():
                sample.mkdir()
                shutil.copy(self.coal / "toAIMMS" / f"GlobalDataToAIMMS_{year}_{itr:02d}.txt", sample)
                shutil.copy(out_file, sample)
        except OSError:
            pass   # the log must never stop a run

    def close(self):
        if self.proc.poll() is None:
            self._request("req_quit := 1 ;\n")
            try:
                self.proc.wait(60)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.showreel:   # keep the raw AIMMS / solver log next to the showreel lines
            try:
                log = self.run / "main" / "wrapper" / "log" / "messages.log"
                if log.exists():
                    SHOWREEL.mkdir(parents=True, exist_ok=True)
                    shutil.copy(log, SHOWREEL / f"coal_solver_log_{time.strftime('%Y%m%d_%H%M%S')}.txt")
            except OSError:
                pass


def _prices(o: dict, year: int) -> dict[str, np.ndarray]:
    """The year's column of each coal price the CMM wrote, (11,), 1987$/MMBtu."""
    j = year - 1990
    out = {}
    for k in PRICE_OUT:
        name = k.replace("/", "_").upper()
        if name in o:
            out[k] = to_array(o[name], (11, 61))[:, j]
    return out


def reference(first: int = FIRST, last: int = 2050, itrs: int = 2, run: Path = RUN_DIR) -> dict:
    """The CMM on cb2026's own inputs, every year, `itrs` iterations: {"prices": {year: {key: (11,)}},
    "production": {year: (11, 17) COALPROD2 column}, "seconds": {year: s}}, saved to run/reference.pkl."""
    p = CoalProcess(run, source="reference (cb2026 inputs)")
    res = {"prices": {}, "production": {}, "seconds": {}}
    try:
        for y in range(first, last + 1):
            sec = 0.0
            for i in range(1, itrs + 1):
                o, s = p.call(y, i, fcrl=int(i == itrs))
                sec += s
            res["prices"][y] = _prices(o, y)
            if "COALREP_COALPROD2" in o:
                res["production"][y] = to_array(o["COALREP_COALPROD2"], (11, 17, 61))[:, :, y - 1990]
            res["seconds"][y] = sec
            print(y, f"{sec:.1f} s", flush=True)
    finally:
        p.close()
    with open(Path(run) / "reference.pkl", "wb") as f:
        pickle.dump(res, f)
    return res


class AimmsCoal:
    """EIA's CMM as run_model's coal market (coal="aimms"). One AIMMS process per cycle."""

    def __init__(self, start_year: int = 2027, calibrate: bool = True, run: Path = RUN_DIR, cycle: int = 1):
        self.snap = Snapshot()
        self.start = start_year
        self.eia = {k: np.asarray(self.snap[k], dtype=np.float64) for k in PRICE_OUT}
        self.factor = {k: np.ones((11, 61)) for k in PRICE_OUT}
        if calibrate:
            ref = Path(run) / "reference.pkl"
            if not ref.exists():
                raise FileNotFoundError(f"{ref}: run python -m nems_open.coal.aimms_couple first (about 3 min)")
            with open(ref, "rb") as f:
                outs = pickle.load(f)["prices"]
            for y, pr in outs.items():
                j = y - 1990
                for k, mine in pr.items():
                    self.factor[k][:, j] = np.divide(self.eia[k][:, j], mine, out=np.ones(11), where=mine > 0)
        self.base = {k: np.asarray(self.snap[k], dtype=np.float64) for k in
                     Q_IN + P_IN + ("COALEMM/QCLCLNR", "COALEMM/EMM_CL_BTUS")}
        self.out = {k: v.copy() for k, v in self.eia.items()}
        self.production = {}
        self.seconds = 0.0
        self.p = CoalProcess(run, source="run_model coal='aimms'")
        self.p.cycle = cycle
        self.itr = 0
        try:
            for y in range(FIRST, start_year):
                self._call(y, 1, None)
                self._call(y, 2, None, fcrl=1)
        except Exception:
            self.close()
            raise

    def _call(self, year, itr, arrays, fcrl=0):
        o, sec = self.p.call(year, itr, arrays, fcrl)
        self.seconds += sec
        self.itr = itr
        j = year - 1990
        for k, v in _prices(o, year).items():
            self.out[k][:, j] = v * self.factor[k][:, j]
        if "COALREP_COALPROD2" in o:
            self.production[year] = to_array(o["COALREP_COALPROD2"], (11, 17, 61))[:, :, j]

    def inputs(self, year: int, q: dict, prices: dict) -> dict:
        """The input arrays that differ from cb2026's: the loop's coal use and fuel prices for this year."""
        j = year - 1990
        arrays = {}
        for k in Q_IN:
            a = self.base[k].copy()
            lk = _loop_key(k)
            if lk in q:
                a[:, j] = q[lk][:, j]
            arrays[k] = a
        for k in P_IN:
            a = self.base[k].copy()
            lk = _loop_key(k)
            if lk in prices:
                a[:, j] = prices[lk][:, j]
            arrays[k] = a
        b, now = self.base["QBLK/QCLEL"][10, j], arrays["QBLK/QCLEL"][10, j]
        ratio = now / b if b > 0 else 1.0
        for k in ("COALEMM/QCLCLNR", "COALEMM/EMM_CL_BTUS"):   # power coal by coal region and plant, scaled
            a = self.base[k].copy()
            a[:, j, ...] *= ratio
            arrays[k] = a
        return arrays

    def begin(self, year: int, itr: int, q: dict, prices: dict, fcrl: int = 0):
        self._call(year, itr, self.inputs(year, q, prices), fcrl)

    def prices(self) -> dict[str, np.ndarray]:
        return {k: v.copy() for k, v in self.out.items()}

    def close(self):
        self.p.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    reference(int(a[0]) if a else FIRST, int(a[1]) if len(a) > 1 else 2050)
