"""Prepare a run folder for the Fortran oracle.

Writes into oracle/run/:
  filelist.txt     NEMS file key -> path, from the scenario's scedes file
  options.txt      scedes switches for RTOVALUE
  dump/*.bin       each restart variable the commercial module can see, raw bytes
  input/*.rng      spreadsheet named ranges, flattened for readrng_stub.f90
And into oracle/build/:
  load_restart.f90 Fortran that reads dump/*.bin into the COMMON blocks

Usage: python -I gen_oracle.py <upstream> <scenario> [module]   e.g. ../nems-upstream cb2026 resd
module is comm (default, run/ and build/) or resd (run_resd/ and build_resd/).
"""

import re
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# One entry per ported module. includes: same includes, same order, as the module's
# entry routine sees them (nested includes such as apq -> qblk are followed).
# workbooks: spreadsheets read through ReadRngXLSX, as (file, sheet).
# skip_blocks: restart blocks the module itself writes. They are not loaded, so any
# match against EIA is earned.
MODULES = {
    "comm": dict(
        source="comm.f", run="run", build="build",
        includes=["parametr", "ncntrl", "apq", "macout", "eusprc", "qsblk", "mxpblk", "uefpout",
                  "uecpout", "emission", "emmparm", "steoblock", "cogen", "bldglrn", "commrep",
                  "tranrep", "e111d", "comparm"],
        workbooks=[("input/cdm/ktekx.xlsx", "ktek")],
        skip_blocks=[],
    ),
    "resd": dict(
        source="resd.f", run="run_resd", build="build_resd",
        # MODULE R_ at the top of resd.f
        includes=["parametr", "ncntrl", "apq", "resdrep", "rtek", "bldglrn", "emmparm", "emission",
                  "eusprc", "emablk", "macout", "rscon", "rseff", "qsblk", "cogen", "uefpout",
                  "uecpout", "e111d", "steoblock",
                  "tranrep"],  # included by EXCONS and NEMSCN: TRQ_ELEC, EV home charging
        workbooks=[("input/rdm/rsmess.xlsx", s) for s in ("RSCLASS", "RSMEQP", "RSSWITCH", "RSMSHL")],
        skip_blocks=["RESDREP", "RSCON", "RSEFF"],
    ),
    "ind": dict(
        source="ind.f", run="run_ind", build="build_ind",
        # MODULE I_ at the top of ind.f, then the extra includes its routines add
        includes=["parametr", "ccatsdat", "ncntrl", "emmparm", "macout", "qblk", "mpblk", "intout", "epmmpblk",
                  "qsblk", "eusprc", "indout", "cogen", "indrep", "bifurc", "wrenew", "ogsmout", "pmmrpt",
                  "pmmout", "ngtdmrep", "comparm", "tranrep", "cdsparms",
                  "hmmblk", "ghgrep", "emeblk", "emission", "steoblock", "indepm", "coalrep", "coalout",
                  "lfmmout", "emoblk", "convfact", "ab32"],
        workbooks=[("input/idm/indcogenx.xlsx", "icogen")]
                  + [("input/idm/ironstlx.xlsx", s) for s in ("steel", "paper", "Aluminum", "Glass", "Lime", "Cement")],
        # Nothing is skipped: IND reads the current year's quantities (calgen divides by QGFIN)
        # and next year's consumption (AGCON, ... in CARBSHRCA) before it writes them, so the
        # run starts from the restart file's values, as NEMS does from its seed restart.
        skip_blocks=[],
    ),
}

# Set by main() from MODULES.
RUN = HERE / "run"
BUILD = HERE / "build"
INCLUDES: list[str] = []
WORKBOOKS: list = []
SKIP_BLOCKS: list[str] = []

# Must match build.sh. The include path goes through oracle/upstream_link, a junction
# to the EIA checkout (NEMS_UPSTREAM), because gfortran's -I breaks on spaces.
FFLAGS = ["-ffree-line-length-none", "-fdec", "-I../upstream_link/includes"]


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


def write_filelist(upstream: Path, scenario: str):
    rows, opts = [], []
    for line in (upstream / "scedes" / f"scedes.{scenario}.csv").read_text(encoding="latin-1").splitlines():
        parts = line.split(",")
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        key, value = parts[0].strip(), parts[1].strip()
        if value.startswith("$NEMS/"):
            path = (upstream / value[len("$NEMS/"):]).resolve()
            rows.append(f"{key[:-1] if key.endswith('N') else key} {path}")
        elif re.fullmatch(r"-?\d+", value):
            opts.append(f"{key} {value}")
    (RUN / "filelist.txt").write_text("\n".join(rows) + "\n")
    (RUN / "options.txt").write_text("\n".join(opts) + "\n")
    return rows


def flatten_workbooks(upstream: Path):
    """Named ranges for readrng_stub.f90, one file per (workbook, sheet) read."""
    (RUN / "input").mkdir(exist_ok=True)
    for book, sheet in WORKBOOKS:
        out = RUN / "input" / f"{Path(book).stem}.{sheet}.rng"
        subprocess.run([sys.executable, "-I", str(HERE / "xlsx_ranges.py"),
                        str(upstream / book), sheet, str(out)], check=True)


def common_aliases(inc_dir: Path, includes):
    """{(BLOCK, name): [other names]} for COMMON blocks that two includes declare with
    different variable names over the same memory (ampblk calls the industrial
    electricity price PELIN, epmmpblk calls it AELIN). The restart file keeps one
    spelling; the other include needs its own copy loaded."""
    lists = {}
    wanted = {m.group(1).upper() for n in includes
              for st in statements((inc_dir / n).read_text(encoding="latin-1"))
              if (m := re.match(r"common\s*/\s*(\w+)\s*/", st, re.I))}
    # The other spelling usually lives in an include the module does not pull in, so scan them all.
    for f in sorted(inc_dir.iterdir()):
        if not f.is_file():
            continue
        for st in statements(f.read_text(encoding="latin-1")):
            m = re.match(r"common\s*/\s*(\w+)\s*/(.*)", st, re.I)
            if m and m.group(1).upper() in wanted:
                body = re.sub(r"\([^()]*\)", "", m.group(2))
                names = [v.strip().lower() for v in body.split(",") if v.strip()]
                lists.setdefault(m.group(1).upper(), []).append(names)
    aliases = {}
    for block, ls in lists.items():
        for a in ls:
            for b in ls:
                if a is not b and len(a) == len(b):
                    for x, y in zip(a, b):
                        if x != y:
                            aliases.setdefault((block, x), set()).add(y)
    return aliases


def dump_restart(upstream: Path, scenario: str, members, aliases=None):
    aliases = aliases or {}
    runs = sorted((upstream / "output" / "aeo2026" / scenario).glob("*/restart.npz"))
    z = np.load(runs[0], allow_pickle=False)
    dump = RUN / "dump"
    dump.mkdir(parents=True, exist_ok=True)
    loaded = []
    for key in z.files:
        block, _, var = key.partition("/")
        wanted = [(block.upper(), var.lower())] + [(block.upper(), o) for o in aliases.get((block.upper(), var.lower()), ())]
        if not any(w in members for w in wanted) or block.upper() in SKIP_BLOCKS:
            continue
        try:
            a = z[key]
        except ValueError:  # text arrays need pickle; numeric commons only
            continue
        if a.dtype.kind not in "iuf":
            continue
        fname = f"{block}__{var}.bin".lower()
        (dump / fname).write_bytes(np.asfortranarray(a).tobytes(order="F"))
        if (block.upper(), var.lower()) in members:
            loaded.append((var.upper(), fname))
        for other in sorted(aliases.get((block.upper(), var.lower()), ())):
            if (block.upper(), other) in members and not any(v == other.upper() for v, _ in loaded):
                oname = f"{block}__{other}.bin".lower()
                (dump / oname).write_bytes(np.asfortranarray(a).tobytes(order="F"))
                loaded.append((other.upper(), oname))
    return loaded


def include_prefixes(source: Path):
    """For each include, the include list of the first comm.f routine that uses it,
    up to and including it. That ordering already compiles, so it is safe."""
    prefixes = {}
    for routine in re.split(r"(?im)^\s*end\s*(?:subroutine|function)?\s*\w*\s*$", source.read_text(encoding="latin-1")):
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


def write_loader(loaded, inc_dir: Path, source: Path):
    """One loader routine per include file, each with an include order that compiles."""
    prefixes = include_prefixes(source)
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
    upstream, scenario = Path(sys.argv[1]).resolve(), sys.argv[2]
    mod = MODULES[sys.argv[3] if len(sys.argv) > 3 else "comm"]
    RUN, BUILD = HERE / mod["run"], HERE / mod["build"]
    INCLUDES, WORKBOOKS, SKIP_BLOCKS = mod["includes"], mod["workbooks"], mod["skip_blocks"]
    RUN.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    link = HERE / "upstream_link"
    if not link.exists():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(upstream)], check=True, capture_output=True)
    inc_dir = upstream / "includes"
    includes = walk_includes(INCLUDES, inc_dir)
    members = common_members(inc_dir, includes)
    rows = write_filelist(upstream, scenario)
    flatten_workbooks(upstream)
    loaded = dump_restart(upstream, scenario, members, common_aliases(inc_dir, includes))
    subprocess.run([sys.executable, str(HERE / "steo_fill.py"), str(upstream),
                    str(RUN / "dump" / "steo_var_com__eq.bin")], check=True)
    n = write_loader(loaded, inc_dir, upstream / "source" / mod["source"])
    print(f"{len(includes)} includes, {len(loaded)} restart variables dumped, {n} wired into the loader, {len(rows)} files")


if __name__ == "__main__":
    main()
