"""EIA's real LFMM (GAMS) as run_model's refining module: run(lfmm="gams").

How NEMS runs LFMM (refine.f): every iteration of every year from 2010 it writes NEM_TO_LFMM1.gdx and calls
`gams LFshell.gms`; LFMM carries its builds between years in LFMM_Builds.gdx, GrossCapacity.gdx and Grossdumfact.gdx
and only builds on the year's final iteration (FCRL=1).

Here: years before start_year come from the reference sequence (gams_run.sequence on cb2026's own inputs, 2010 to
2050, in REFERENCE): its state after start_year - 1 seeds a separate run folder. Each loop iteration that calls LFMM
writes cb2026's restart arrays with the loop's current year column of every QBLK and MPBLK array, solves (GAMS's Linux
build in WSL, HiGHS, about 2 minutes), and reads LFMM_to_NEMS.gdx. A solve is about 2 minutes, so LFMM runs on a year's
first iteration and on its final one (FCRL=1, where it builds); iterations in between reuse the first answer.

calibrate: one LFMM pass on cb2026's final inputs lands off EIA's restart (EIA's is the end of several iterations
and cycles, solved with Xpress). With calibrate each output is EIA's value times LFMM's own now over LFMM's own in the
reference sequence, so the baseline is EIA's and a run's moves are LFMM's.

Every solve appends one line to SHOWREEL/lfmm.jsonl (size, solver, time, objective, headline prices); the sample
year's input and output GDX files are kept once. The log never feeds back into results.

carbon: the loop's carbon price (1987 $ per metric ton CO2, by year) is written as NEMS's EMETAX and EMABLK J
adders (nems_open/carbon_inputs.py), so LFMM prices its own refinery emissions; CO2PLFMM stays cb2026's 0, so carbon
is added to product prices outside LFMM, by the supply side, as in NEMS.

Infeasible solves: EIA's shell keeps going when LFMM is infeasible (it copies the listing to INFEAS.<year>.<cycle>.<itr>.lst
and NEMS uses what it had). Here an infeasible solve on a year that already has a solve this cycle keeps that solve,
saves the listing the same way, puts back the carried state (LFMM_Builds.gdx, GrossCapacity.gdx, Grossdumfact.gdx)
from before the solve, and is counted in self.infeasible ((year, itr) pairs). A year's first solve that is
infeasible still raises: there is nothing to keep.

Not passed: Brent. LFMM prices crude on the international model's supply curves (INTOUT), which stay cb2026's; an
oil price lever moves product prices through the supply stand-in, not here.
"""

import json
import os
import re
import shutil
import time
from pathlib import Path

import numpy as np

from nems_open.lfmm import gams_io, gams_run
from nems_open.lfmm.standin import RF_IN_INDUSTRY, LfmmResult, fold

REFERENCE = Path(os.environ.get("NEMS_LFMM_REFERENCE", Path.home() / "dev" / "oracle-cache" / "lfmm-gams"))
RUN_DIR = Path(os.environ.get("NEMS_LFMM_RUN", Path.home() / "dev" / "oracle-cache" / "lfmm-gams-run"))
SHOWREEL = Path(os.environ.get("NEMS_SHOWREEL", Path.home() / "dev" / "aimms-showreel"))
SAMPLE_YEAR = 2030
US = 10


def solve_info(log: Path) -> dict:
    """Size, status, objective and times from a GAMS log of one LFMM solve."""
    out = {}
    if not Path(log).exists():
        return out
    t = Path(log).read_text(errors="replace")
    if m := re.search(r"---\s+([\d,]+) rows\s+([\d,]+) columns\s+([\d,]+) non-zeroes", t):
        out["rows"], out["columns"], out["nonzeros"] = (int(x.replace(",", "")) for x in m.groups())
    if m := re.search(r"Model status\s*:\s*(.+)", t):
        out["status"] = m.group(1).strip()
    if m := re.search(r"Objective value\s*:\s*(\S+)", t):
        out["objective"] = float(m.group(1))
    if m := re.search(r"HiGHS run time\s*:\s*(\S+)", t):
        out["solver_time_s"] = float(m.group(1))
    if m := re.search(r"\(solvestat, modelstat\): \((\d+), (\d+)\)", t):
        out["solvestat"], out["modelstat"] = int(m.group(1)), int(m.group(2))
    out["solver"] = "HiGHS" if "HiGHS" in t else None
    return out


def columns(o: dict, year: int) -> dict[str, np.ndarray]:
    """LFMM's MPBLK and QBLK outputs for one year as loop keys ("MPBLK/pmgtr") -> (11,) arrays."""
    out = {}
    for name, d in o.items():
        block, _, var = name.partition("_")
        if block not in ("MPBLK", "QBLK"):
            continue
        a = np.zeros(11)
        for k, v in d.items():
            if len(k) == 2 and k[1].startswith(str(year)) and k[0][:2].isdigit():
                a[int(k[0][:2]) - 1] = v
        out[f"{block}/{var.lower()}"] = a
    return out


STATE = ("LFMM_Builds.gdx", "GrossCapacity.gdx", "Grossdumfact.gdx")

# HiGHS options per attempt: defaults first, then interior point with crossover, then primal simplex.
# Every attempt gets a time limit: a healthy LFMM solve takes under three minutes, while the 2030 cycle 2 dual
# simplex stalled for 15 minutes and then crashed the solver with bad_alloc.
TIME_LIMIT = 300   # healthy solves finish in under 90 s; the 2049 stall sat 1,400 s on 300 iterations
RETRY_OPTIONS = ("", "solver = ipm\nrun_crossover = on\n", "solver = simplex\nsimplex_strategy = 4\n")


def solver_failed(rc: int, info: dict, log: str = "") -> bool:
    """The solver gave no answer: solvestat 13 or Not Set (2039 crash), solvestat 3 (time limit hit), or the
    solver process died mid-solve (GAMS rc != 0, no solve summary, HiGHS output in the log: 2030 bad_alloc)."""
    if info.get("solvestat") == 3:   # 2049 cycle 2: time limit hit, GAMS rc 6
        return True
    if rc == 0:
        return info.get("solvestat") == 13 or info.get("status") == "Not Set"
    return info.get("status") is None and ("HiGHS" in log or "bad_alloc" in log)


class LfmmInfeasible(RuntimeError):
    """LFMM solved but the model is infeasible."""


class LfmmGams:
    """EIA's LFMM for the loop, one run folder, one GAMS process per call (single process: RAM is the limit)."""

    def __init__(self, start_year: int, base: dict, cycle: int = 1, calibrate: bool = True,
                 run: Path = RUN_DIR, reference: Path = REFERENCE, showreel: bool = True, timeout: float = 1800,
                 carbon=None):
        self.start, self.base, self.cycle, self.calibrate = start_year, base, cycle, calibrate
        self.run, self.reference, self.showreel, self.timeout = Path(run), Path(reference), showreel, timeout
        self.arrays = gams_run.restart_arrays()
        if carbon is not None:
            from nems_open import carbon_inputs
            self.arrays.update(carbon_inputs.arrays(carbon, self.arrays))
        gams_run.prepare(self.run, start_year, self.arrays)
        gams_run.load_state(self.run, self.reference, start_year - 1)
        self._ref, self._last, self.infeasible = {}, {}, []
        self.solver_failures = []
        self.fallbacks = []   # (year, itr) whose first solve this cycle failed and used the reference sequence's

    def reference_columns(self, year: int) -> dict[str, np.ndarray]:
        if year not in self._ref:
            g = self.reference / f"LFMM_to_NEMS_{year}.gdx"
            if not g.exists():
                raise FileNotFoundError(f"{g}: run the reference sequence through {year} first")
            self._ref[year] = columns(gams_io.read_outputs(g), year)
        return self._ref[year]

    def _inputs(self, j: int, q: dict, col: dict, prices: dict) -> dict:
        a = dict(self.arrays)
        for k, v in {**q, **prices}.items():
            K = k.upper()
            if K in a and np.ndim(a[K]) == 2 and a[K].shape[1] > j:
                x = np.array(a[K], dtype=np.float64)
                x[:, j] = col[k] if k in col else v[:, j]
                a[K] = x
        return a

    def call(self, year: int, itr: int, fcrl: int, arrays: dict) -> dict[str, np.ndarray]:
        gams_run.prepare(self.run, year, arrays, itr=itr, fcrl=fcrl, cycle=self.cycle, fresh=False)
        (self.run / "LFMM.log").unlink(missing_ok=True)
        (self.run / "LFMM_to_NEMS.gdx").unlink(missing_ok=True)
        kept = {f: (self.run / f).read_bytes() for f in STATE if (self.run / f).exists()}
        opt = self.run / "highs.opt"
        for attempt, options in enumerate(RETRY_OPTIONS):
            if attempt:   # the solver failed: restore the build state and retry with sturdier options
                for f, b in kept.items():
                    (self.run / f).write_bytes(b)
                (self.run / "LFMM.log").unlink(missing_ok=True)
            opt.write_text(f"time_limit = {TIME_LIMIT}\n" + options)
            t = time.time()
            rc = gams_run.gams(self.run, timeout=self.timeout)
            sec = time.time() - t
            info = solve_info(self.run / "LFMM.log")
            log = (self.run / "LFMM.log").read_text(errors="replace") if (self.run / "LFMM.log").exists() else ""
            gams_run.clean_dumps(self.run)
            if not solver_failed(rc, info, log):
                break
            self.solver_failures.append((year, itr, attempt))
        opt.unlink(missing_ok=True)
        if solver_failed(rc, info, log):   # every option set failed: treat as EIA's shell treats an infeasible solve
            for f, b in kept.items():
                (self.run / f).write_bytes(b)
            raise LfmmInfeasible(f"LFMM {year} itr {itr}: solver failed ({info.get('status')}); see {self.run / 'LFMM.log'}")
        if rc == 0 and info.get("modelstat") == 4:
            lst = self.run / "LFshell.lst"
            if lst.exists():
                shutil.copy(lst, self.run / f"INFEAS.{year}.{self.cycle}.{itr}.lst")
            for f, b in kept.items():
                (self.run / f).write_bytes(b)
            raise LfmmInfeasible(f"LFMM {year} itr {itr}: infeasible; see {self.run / 'LFMM.log'}")
        if rc != 0 or info.get("modelstat") != 1 or not (self.run / "LFMM_to_NEMS.gdx").exists():
            raise RuntimeError(f"LFMM {year} itr {itr}: rc {rc}, {info.get('status')}; see {self.run / 'LFMM.log'}")
        out = columns(gams_io.read_outputs(self.run / "LFMM_to_NEMS.gdx"), year)
        if self.showreel:
            self._log(year, itr, fcrl, sec, info, out)
        return out

    def solve_year(self, j: int, q: dict, col: dict, prices: dict, itr: int, fcrl: int) -> LfmmResult:
        """One loop iteration for year index j (as LfmmStandin.solve_year): columns (11,) of product prices,
        refinery fuel (QBLK q*rf) and industrial fuel with the refinery change folded in."""
        year = 1990 + j
        if itr == 1 or fcrl == 1 or year not in self._last:
            try:
                self._last[year] = self.call(year, itr, fcrl, self._inputs(j, q, col, prices))
            except LfmmInfeasible:
                if year not in self._last:   # nothing solved yet this cycle: fall back to EIA's own reference solve
                    self._last[year] = self.reference_columns(year)
                    self.fallbacks.append((year, itr))
                self.infeasible.append((year, itr))
        now = self._last[year]
        b = self.base
        out = {}
        ref = self.reference_columns(year) if self.calibrate else {}
        for k, v in now.items():
            if k not in b:
                continue
            if self.calibrate:
                r, e = ref.get(k), b[k][:, j]
                ratio = np.ones(11) if r is None else np.divide(v, r, out=np.ones(11), where=np.abs(r) > 1e-9)
                out[k] = np.where(e > 0, e * ratio, e)
            else:
                out[k] = v
        price = {k: v for k, v in out.items() if k.startswith("MPBLK/")}
        refinery = {k: v for k, v in out.items() if k.startswith("QBLK/") and k.endswith("rf")}
        ind = {}
        for f in RF_IN_INDUSTRY:
            k, rf = f"QBLK/q{f}in", f"QBLK/q{f}rf"
            if k in b and rf in refinery:
                start = np.asarray(col[k] if k in col else q[k][:, j], dtype=np.float64)
                held = b[rf][:, j] if k in col else q[rf][:, j]
                ind[k] = fold(start, refinery[rf] - held)
        return LfmmResult(price, refinery, ind)

    def _log(self, year, itr, fcrl, sec, info, out):
        """One JSON line per solve in SHOWREEL/lfmm.jsonl, and the sample year's GDX files once."""
        try:
            SHOWREEL.mkdir(parents=True, exist_ok=True)
            h = {k.split("/")[1]: round(float(out[k][US]), 4) for k in
                 ("MPBLK/pmgtr", "MPBLK/pdstr", "MPBLK/pjftr", "MPBLK/prltr") if k in out}
            line = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": "refining (EIA LFMM, LFshell.gms)",
                    "year": year, "cycle": self.cycle, "iteration": itr, "fcrl": fcrl,
                    "rows": info.get("rows"), "columns": info.get("columns"), "nonzeros": info.get("nonzeros"),
                    "solver": info.get("solver"), "status": info.get("status"), "objective": info.get("objective"),
                    "solver_time_s": info.get("solver_time_s"), "call_time_s": round(sec, 3),
                    "headline": {"us_prices_87usd_mmbtu": h}}
            with open(SHOWREEL / "lfmm.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
            sample = SHOWREEL / f"lfmm_sample_{SAMPLE_YEAR}"
            if year == SAMPLE_YEAR and itr == 1 and not sample.exists():
                sample.mkdir()
                for f in ("NEM_TO_LFMM1.gdx", "LFMM_to_NEMS.gdx"):   # not LFMM.log: it carries the licence header
                    shutil.copy(self.run / f, sample / f)
        except OSError:
            pass   # the log must never stop a run
