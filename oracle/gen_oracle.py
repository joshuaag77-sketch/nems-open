"""Prepare a run folder for the Fortran oracle.

Writes into oracle/run/:
  filelist.txt     NEMS file key -> path, from the scenario's scedes file
  options.txt      scedes switches for RTOVALUE
  dump/*.bin       each restart variable the commercial module can see, raw bytes
  input/*.rng      spreadsheet named ranges, flattened for readrng_stub.f90
And into oracle/build/:
  load_restart.f90 Fortran that reads dump/*.bin into the COMMON blocks

Usage: python -I gen_oracle.py <upstream> <scenario> [module]   e.g. ../nems-upstream cb2026 tran
module is comm (default, run/ and build/), resd, emm or tran (run_<module>/ and build_<module>/).
The build folder also gets a copy of the upstream includes in inc/, so the compile
works wherever the upstream checkout lives (spaces in its path break -I).
"""

import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("NEMS_ORACLE_WORK", HERE))   # build and run folders (see hooks.py)

# One entry per ported module. includes: same includes, same order, as the module's
# entry routine sees them (nested includes such as apq -> qblk are followed).
# workbooks: spreadsheets read through ReadRngXLSX, as (file, sheet).
# skip_blocks: restart blocks the module itself writes. They are not loaded, so any
# match against EIA is earned.
MODULES = {
    "comm": dict(
        source=["comm.f"], run="run", build="build",
        includes=["parametr", "ncntrl", "apq", "macout", "eusprc", "qsblk", "mxpblk", "uefpout",
                  "uecpout", "emission", "emmparm", "steoblock", "cogen", "bldglrn", "commrep",
                  "tranrep", "e111d", "comparm"],
        workbooks=[("input/cdm/ktekx.xlsx", "ktek")],
        skip_blocks=[],
    ),
    "tran": dict(
        source=["tran.f", "tranfrt.f", "tranair.f"], run="run_tran", build="build_tran",
        # Every include in the three files: MODULE T_, F_ and AIRMOD plus the routines.
        includes=["parametr", "ncntrl", "apq", "aponroad", "qsblk", "macout", "cdsparms", "coalout",
                  "convfact", "tranrep", "tranmain", "intout", "ngtdmout", "angtdm", "aeusprc",
                  "eusprc", "ampblk", "lfmmout", "ngtdmrep", "ogsmout", "pmmout", "pmmrpt",
                  "steoblock"],
        workbooks=[("input/tdm/trnldvx.xlsx", "trnldv"), ("input/tdm/trnnhtsax.xlsx", "trnnhtsa"),
                   ("input/tdm/trnairx.xlsx", "trnair")]
                  + [("input/tdm/trnhdvx.xlsx", s) for s in ("trnhdv", "tech_adopt", "ACT", "Phase_2")],
        skip_blocks=[],
    ),
    "resd": dict(
        source=["resd.f"], run="run_resd", build="build_resd",
        # MODULE R_ at the top of resd.f
        includes=["parametr", "ncntrl", "apq", "resdrep", "rtek", "bldglrn", "emmparm", "emission",
                  "eusprc", "emablk", "macout", "rscon", "rseff", "qsblk", "cogen", "uefpout",
                  "uecpout", "e111d", "steoblock",
                  "tranrep"],  # included by EXCONS and NEMSCN: TRQ_ELEC, EV home charging
        workbooks=[("input/rdm/rsmess.xlsx", s) for s in ("RSCLASS", "RSMEQP", "RSSWITCH", "RSMSHL")],
        skip_blocks=["RESDREP", "RSCON", "RSEFF"],
    ),
    # EMM's Fortran: the yearly driver UTIL and everything it calls, with only the
    # ECP and EFD solves swapped out (see hooks.py). includes="auto" takes every
    # include these files use. EFP's own outputs are not loaded.
    "emm": dict(
        source=["util.f", "udat.f", "uldsm.f", "uefp.f", "uefd.f", "uecp.f", "unugs.f", "udaf.f", "ucape.f",
                "uread.f"],
        run="run_emm", build="build_emm", includes="auto",
        # Every sheet EMM reads through ReadRngXLSX (udat.f RDBD_UECP, uefp.f ELRDFR).
        workbooks=[("input/emm/ecpdaty.xlsx", s) for s in (
                       "GENERAL", "COSTPERF", "SUBSIDY", "CCSRET", "BLDINFO", "OVERWRT", "OPTLRN", "RETROFIT",
                       "FINANCIAL", "RESCES", "FUELTRAN", "SPNRSV", "HTRTIMP")]
                  + [("input/emm/finregy.xlsx", s) for s in (
                       "headers_ntl", "ntl_eovdef", "ntl_eovyrs", "ntl_eslcp", "ntl_life", "ntl_bypass",
                       "headers_reg")],
        skip_blocks=["UEFPOUT"],
        # ORACLESW writes EMM's results database (Oracle/Access era name). Output only.
        options={"ORACLESW": 0},
        # EMM opens this one by a relative path, not through the file list.
        copy={"input/emm/emm_db/NEMS_INPUT.db": "emm_db/NEMS_INPUT.db",
              # NEMS's setup copies these into the run folder (scripts/setup/src/nems_setup.py)
              "input/emm/plntdaf.daf": "PLNTTMP.daf", "input/emm/ettdem.daf": "ETTTMP.daf"},
        file_modes=True,
    ),
}

# Set by main() from MODULES.
RUN = WORK / "run"
BUILD = WORK / "build"
INCLUDES: list[str] = []
WORKBOOKS: list = []
SKIP_BLOCKS: list[str] = []

# Must match build.sh. Run from the build folder, which holds its own copy of the includes.
FFLAGS = ["-ffree-line-length-none", "-fdec", "-Iinc"]


def statements(text: str):
    """Free-form Fortran statements with comments and continuations joined."""
    buf = ""
    for line in text.splitlines():
        line = line.split("!", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.endswith("&"):
            buf += line[:-1] + " "
            continue
        yield (buf + line).strip()
        buf = ""


def walk_includes(names, inc_dir: Path, seen=None):
    seen = seen if seen is not None else []
    for n in names:
        n = n.lower()
        if n in seen:
            continue
        seen.append(n)
        text = (inc_dir / n).read_text(encoding="latin-1")
        nested = re.findall(r"^\s*include\s*'(\w+)'", text, re.I | re.M)
        walk_includes(nested, inc_dir, seen)
    return seen


def common_members(inc_dir: Path, includes):
    """{(BLOCK, var)} for every COMMON declared in these includes."""
    members = set()
    for n in includes:
        for st in statements((inc_dir / n).read_text(encoding="latin-1")):
            m = re.match(r"common\s*/\s*(\w+)\s*/(.*)", st, re.I)
            if not m:
                continue
            body = re.sub(r"\([^()]*\)", "", m.group(2))  # drop dimension lists
            for v in body.split(","):
                v = v.strip()
                if re.fullmatch(r"\w+", v):
                    members.add((m.group(1).upper(), v.lower()))
    return members


def write_filelist(upstream: Path, scenario: str, file_modes=False):
    """file_modes (EMM): also list the run-folder files NEMS creates (no $NEMS/
    path), and write filemodes.txt with each file's action, access, form and
    record length from the scedes file, for stubs.f90's FILE_MGR."""
    rows, opts, modes = [], [], []
    text = (upstream / "scedes" / f"scedes.{scenario}.csv").read_text(encoding="latin-1")
    for parts in csv.reader(text.splitlines()):
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        key, value = parts[0].strip(), parts[1].strip()
        path = None
        if value.startswith("$NEMS/"):
            path = Path(os.path.abspath(upstream / value[len("$NEMS/"):]))   # not resolve(): keep a space-free symlink path
            key = key[:-1] if key.endswith('N') else key
            rows.append(f"{key} {path}")
        elif re.fullmatch(r"-?\d+", value):
            opts.append(f"{key} {value}")
        elif file_modes and re.fullmatch(r"[\w.\-]+\.\w+", value):
            path = value
            rows.append(f"{key} {path}")
        mode = parts[-1].split()
        if file_modes and path is not None and len(mode) == 4 and mode[-1].isdigit():
            modes.append(f"{key} {' '.join(mode)} {path}")
    (RUN / "filelist.txt").write_text("\n".join(rows) + "\n")
    (RUN / "options.txt").write_text("\n".join(opts) + "\n")
    if file_modes:
        (RUN / "filemodes.txt").write_text("\n".join(modes) + "\n")
    return rows


def flatten_workbooks(upstream: Path):
    """Named ranges for readrng_stub.f90, one file per (workbook, sheet) read."""
    (RUN / "input").mkdir(exist_ok=True)
    for book, sheet in WORKBOOKS:
        out = RUN / "input" / f"{Path(book).stem}.{sheet}.rng"
        subprocess.run([sys.executable, "-I", str(HERE / "xlsx_ranges.py"),
                        str(upstream / book), sheet, str(out)], check=True)


def dump_restart(upstream: Path, scenario: str, members):
    runs = sorted((upstream / "output" / "aeo2026" / scenario).glob("*/restart.npz"))
    z = np.load(runs[0], allow_pickle=False)
    dump = RUN / "dump"
    dump.mkdir(parents=True, exist_ok=True)
    loaded = []
    for key in z.files:
        block, _, var = key.partition("/")
        if (block.upper(), var.lower()) not in members or block.upper() in SKIP_BLOCKS:
            continue
        try:
            a = z[key]
        except ValueError:  # text arrays need pickle; numeric commons only
            continue
        if a.dtype.kind not in "iuf":
            continue
        fname = f"{block}__{var}.bin".lower()
        (dump / fname).write_bytes(np.asfortranarray(a).tobytes(order="F"))
        loaded.append((var.upper(), fname))
    return loaded


def source_text(sources) -> str:
    return "\n".join(Path(s).read_text(encoding="latin-1") for s in sources)


def auto_includes(sources) -> list[str]:
    """Every include the sources use, parametr first, in order of first use."""
    seen = ["parametr"]
    for n in re.findall(r"(?im)^\s*include\s*'(\w+)'", source_text(sources)):
        if n.lower() not in seen:
            seen.append(n.lower())
    return seen


def include_prefixes(sources):
    """For each include, the include list of the first module or routine that uses it,
    up to and including it. That ordering already compiles, so it is safe."""
    prefixes = {}
    for routine in re.split(r"(?im)^\s*end\s*(?:subroutine|function|module)?\s*\w*\s*$", source_text(sources)):
        seq = [n.lower() for n in re.findall(r"(?im)^\s*include\s*'(\w+)'", routine)]
        for i, n in enumerate(seq):
            prefixes.setdefault(n, seq[: i + 1])
    return prefixes


def compiles(includes) -> bool:
    """Does this include list compile on its own? Checked with gfortran."""
    inc = "\n".join(f"      include '{n}'" for n in includes)
    test = BUILD / "_inc_test.f90"
    test.write_text(f"      subroutine t\n      implicit none\n{inc}\n      end subroutine t\n")
    r = subprocess.run(["gfortran", "-fsyntax-only", *FFLAGS, "_inc_test.f90"],
                       cwd=BUILD, capture_output=True)
    test.unlink()
    return r.returncode == 0


def pick_prefix(top: str, prefixes) -> list[str] | None:
    base = ["parametr", "ncntrl", "macout", "comparm", "comvars"]
    found = prefixes.get(top, [top])
    candidates = [["parametr", top], ["parametr", "ncntrl", top], ["parametr", "emmparm", top],
                  base + [top], found if "parametr" in found else ["parametr"] + found]
    return next((c for c in candidates if compiles(c)), None)


def write_loader(loaded, inc_dir: Path, sources):
    """One loader routine per include file, each with an include order that compiles."""
    prefixes = include_prefixes(sources)
    routines, calls, done = [], [], set()
    for top in INCLUDES:
        if top == "parametr":
            continue
        members = common_members(inc_dir, walk_includes([top], inc_dir))
        mine = [(v, f) for v, f in loaded if (f.split("__")[0].upper(), v.lower()) in members and f not in done]
        if not mine:
            continue
        prefix = pick_prefix(top, prefixes)
        if prefix is None:
            print(f"  skipped {top}: no include order compiles")
            continue
        done.update(f for _, f in mine)
        inc = "\n".join(f"      include '{n}'" for n in prefix)
        body = "\n".join(f"      call ld('{f}', sizeof({v}), {v}, nbad)" for v, f in sorted(mine))
        routines.append(f"""      subroutine load_{top}(nbad)
      implicit none
{inc}
      integer nbad
{body}
      end subroutine load_{top}
""")
        calls.append(f"      call load_{top}(nbad)")
    # STEO block: not in the restart file, rebuilt by steo_fill.py as NEMS does at startup.
    routines.append("""      subroutine load_steo(nbad)
      implicit none
      include 'parametr'
      include 'steoblock'
      integer nbad
      call ld('steo_var_com__eq.bin', sizeof(EQ_STEO_VARS), EQ_STEO_VARS, nbad)
      end subroutine load_steo
""")
    calls.append("      call load_steo(nbad)")
    calls_txt = "\n".join(calls)
    src = f"""! Generated by gen_oracle.py. Do not edit.
      subroutine load_restart(nbad)
      implicit none
      integer nbad
      nbad = 0
{calls_txt}
      end subroutine load_restart

{"".join(routines)}
"""
    (BUILD / "load_restart.f90").write_text(src)
    return len(done)


def main():
    global RUN, BUILD, INCLUDES, WORKBOOKS, SKIP_BLOCKS
    upstream, scenario = Path(os.path.abspath(sys.argv[1])), sys.argv[2]   # abspath, not resolve: keep a space-free symlink path
    mod = MODULES[sys.argv[3] if len(sys.argv) > 3 else "comm"]
    RUN, BUILD = WORK / mod["run"], WORK / mod["build"]
    sources = [upstream / "source" / s for s in ([mod["source"]] if isinstance(mod["source"], str) else mod["source"])]
    INCLUDES, WORKBOOKS, SKIP_BLOCKS = mod["includes"], mod["workbooks"], mod["skip_blocks"]
    if INCLUDES == "auto":
        INCLUDES = auto_includes(sources)
    RUN.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    shutil.copytree(upstream / "includes", BUILD / "inc", dirs_exist_ok=True)
    inc_dir = upstream / "includes"
    includes = walk_includes(INCLUDES, inc_dir)
    members = common_members(inc_dir, includes)
    rows = write_filelist(upstream, scenario, mod.get("file_modes", False))
    if mod.get("options"):
        opts = dict(l.split(" ", 1) for l in (RUN / "options.txt").read_text().splitlines() if l)
        opts.update({k: str(v) for k, v in mod["options"].items()})
        (RUN / "options.txt").write_text("".join(f"{k} {v}\n" for k, v in opts.items()))
    if mod.get("file_modes"):
        # NEMS starts every run in a fresh folder: drop the files the last run made
        # (EMM's scratch DAFs, reports) and its dump index files (odump appends).
        for row in rows:
            name = row.split(" ", 1)[1]
            if not Path(name).is_absolute():
                (RUN / name).unlink(missing_ok=True)
        for idx in (RUN / "out" / "state").glob("*/*/index.txt"):
            idx.unlink()
    for src, dst in mod.get("copy", {}).items():
        (RUN / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(upstream / src, RUN / dst)
    flatten_workbooks(upstream)
    loaded = dump_restart(upstream, scenario, members)
    subprocess.run([sys.executable, str(HERE / "steo_fill.py"), str(upstream),
                    str(RUN / "dump" / "steo_var_com__eq.bin")], check=True)
    n = write_loader(loaded, inc_dir, sources)
    print(f"{len(includes)} includes, {len(loaded)} restart variables dumped, {n} wired into the loader, {len(rows)} files")


if __name__ == "__main__":
    main()
