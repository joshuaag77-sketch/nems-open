"""Instrument the transportation oracle (tran.f, tranfrt.f, tranair.f).

Writes build_tran/oracle_state_tran.f90 with:
  oracle_zero   clears what the module writes to the restart file, before the run
  oracle_final  dumps TRANREP, TRANMAIN and QBLK after the run (out/state/final/0)
  ost_<tag>     state dump for one routine, called just before and after its CALL
and inserts those calls into the patched sources.

Most of this module's state lives in Fortran MODULE variables (T_ in tran.f, F_ in
tranfrt.f, AIRMOD in tranair.f), not COMMON blocks. A routine's dump holds every
module or COMMON variable named anywhere in the routine or the routines it calls
(followed through the call graph), so dumps stay small. Files for F_ variables are
prefixed "f_" and AIRMOD variables "a_"; T_ and COMMON variables keep their names.
Dumps go to run_tran/out/state/<tag>_in|_out/<year>/ on the FIRST iteration of
DUMP_YEARS, read in Python with nems_open.oracle_state.load(tag, year, run="run_tran").
First, not final: TRAN runs 3 times a year with the same inputs here, so on the
final iteration "_in" already holds the answers and a test would prove nothing.
On the first iteration this year's module values are still empty (MODULE arrays
are not in the restart file), and the CURITR == 1 branches get exercised.

Output only: nothing here changes a computed value.

Usage: python -I hooks_tran.py <upstream> <build_tran folder>
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hooks import declarations, common_names, statements, split_top  # noqa: E402

RUN = HERE / "run_tran"

# 2020, 2025, 2030, 2040, 2050: one history year, the last STEO-benchmarked year,
# and three projection years. Fewer than the commercial set because module state
# here is large (LDV_STOCK alone is 86 MB).
DUMP_YEARS = [31, 36, 41, 51, 61]

# Routine being ported: (tag, file, line in that file that calls it, routine name).
# The dump holds what the routine and its callees can touch.
TARGETS = [
    ("tmac", "tran.f90", r"^\s*CALL TMAC\s*$", "tmac"),
    ("newldv", "tran.f90", r"^\s*CALL NEWLDV\s*$", "newldv"),
    ("tmpgnew", "tran.f90", r"^\s*CALL TMPGNEW\s*$", "tmpgnew"),
    ("treg", "tran.f90", r"^\s*CALL TREG\s*$", "treg"),
    ("tfltstks", "tran.f90", r"^\s*CALL TFLTSTKS\s*$", "tfltstks"),
    ("flthav", "tran.f90", r"^\s*if \(yrs\.ge\.MINVAL\(first_lidar_year\)\) CALL FLTHAV", "flthav"),
    ("tfltvmts", "tran.f90", r"^\s*CALL TFLTVMTS\s*$", "tfltvmts"),
    ("tsmod", "tran.f90", r"^\s*CALL TSMOD\s*$", "tsmod"),
    ("tmpgstk", "tran.f90", r"^\s*CALL TMPGSTK\s*$", "tmpgstk"),
    ("tcurb", "tran.f90", r"^\s*CALL TCURB\s*$", "tcurb"),
    ("tfltmpgs", "tran.f90", r"^\s*CALL TFLTMPGS\s*$", "tfltmpgs"),
    ("tfltcons", "tran.f90", r"^\s*CALL TFLTCONS\s*$", "tfltcons"),
    ("tvmt", "tran.f90", r"^\s*CALL TVMT\s*$", "tvmt"),
    ("tranfrt", "tran.f90", r"^\s*CALL TRANFRT\(0\)\s*$", "tranfrt"),
    ("tmpgag", "tran.f90", r"^\s*CALL TMPGAG\s*$", "tmpgag"),
    ("trail", "tran.f90", r"^\s*CALL TRAIL\s*$", "trail"),
    ("tship", "tran.f90", r"^\s*CALL TSHIP\s*$", "tship"),
    ("tranair", "tran.f90", r"^\s*CALL TRANAIR\s*$", "tranair"),
    ("tmisc", "tran.f90", r"^\s*CALL TMISC\s*$", "tmisc"),
    ("tcons", "tran.f90", r"^\s*CALL TCONS\s*$", "tcons"),
    ("tinteg", "tran.f90", r"^\s*CALL TINTEG\s*$", "tinteg"),
    ("tbenchmark", "tran.f90", r"^\s*CALL TBENCHMARK\s*$", "tbenchmark"),
    ("treport", "tran.f90", r"^\s*CALL TREPORT\s*$", "treport"),
]

# Saved local arrays a routine reads back from last year (see instrument_private).
# {tag: {routine (the target or one it calls): [arrays]}}. Found by scanning for locals
# read at a year index minus something (n-1, iyr-1, ...).
PRIVATE = {
    "trail": {"trail": ["rail_fuel_shr", "lng_locom_inccost", "adoptlng"]},
    "tmisc": {"tmisc": ["hyway", "ftvmt"]},
    "tmpgnew": {"talt2": ["altstat", "predstk"]},
    "tranfrt": {"truck_act": ["credit_2b3_zev", "credit_48v_zev", "credit_78t_zev", "credit_2b3_nzev",
                              "credit_48v_nzev", "credit_78t_nzev", "bank_2b8v_zev", "bank_2b8v_nzev",
                              "bank_78t_zev", "bank_78t_nzev"],
                "truck_techadopt": ["techpenyr_p2"], "truck_ghgmeet": ["ghgbank"],
                "truck_choice": ["cpm_r_ice"], "truck_vmt": ["ttonmi", "tvmt", "temp_stk_vmt_ratio"]},
    "tship": {"tship": ["isfdt_b", "lsfo_upgrade", "temp_prhtr"]},
    "tranair": {"tairt": ["pjftr_us"]},
    "tbenchmark": {"tbenchmark": ["stmgtr_new", "stjftr_new", "stdstr_new", "strstr_new"]},
}

# Shared output blocks, dumped at the end of the run.
FINAL_FILES = ["tranrep", "tranmain", "qblk"]
FINAL_INCLUDES = ["parametr", "ncntrl", "qblk", "tranrep", "tranmain"]

# Includes for the COMMON part of a state dump, in an order that compiles: MODULE T_'s
# own list, then the extra blocks TRAN, TRANFRT and TRANAIR routines include.
COMMON_INCLUDES = ["parametr", "apq", "aponroad", "ncntrl", "qsblk", "macout", "cdsparms", "coalout",
                   "convfact", "tranrep", "tranmain", "intout", "ngtdmout", "eusprc", "pmmout",
                   "pmmrpt", "lfmmout", "ogsmout", "ngtdmrep"]  # steoblock clashes (MPG); TBENCHMARK only

MODULES = [("T_", "tran.f90", ""), ("F_", "tranfrt.f90", "f_"), ("AIRMOD", "tranair.f90", "a_")]

# Blocks that reuse another block's variable names: ANGTDM (natural gas prices, also
# in NGTDMOUT) and AEUSPRC (also in EUSPRC). Routines that include them see these
# values, so they are dumped as <include>__<name>, e.g. angtdm__pgftrfv (TMISC).
ALT_INCLUDES = ["angtdm", "aeusprc"]

START = re.compile(r"^\s*(?:(?:real|integer|logical)(?:\*\d|\(\w+\))?\s+)?(?:recursive\s+)?"
                   r"(subroutine|function)\s+(\w+)", re.I | re.M)
KIND = [(re.compile(r"\b(real|integer|logical)\s*\(\s*(?:kind\s*=\s*)?(\d)\s*\)", re.I), r"\1*\2")]


def code_only(text):
    """Source with comments and string literals removed, for identifier scans."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"'[^']*'|\"[^\"]*\"", "''", line)
        out.append(line.split("!", 1)[0])
    return "\n".join(out)


def normalise(text):
    for pat, rep in KIND:
        text = pat.sub(rep, text)
    return text


def module_body(text, name):
    m = re.search(rf"^\s*module\s+{name}\s*$(.*?)^\s*end\s+module", text, re.I | re.M | re.S)
    return m.group(1)


def parameters(text):
    names = set()
    for st in statements(text):
        m = re.match(r"parameter\s*\((.*)\)\s*$", st, re.I)
        if m:
            names.update(re.match(r"\s*(\w+)", p).group(1).lower() for p in split_top(m.group(1)))
        m = re.match(r"\w[^:]*,\s*parameter\b[^:]*::(.*)", st, re.I)
        if m:
            names.update(re.match(r"\s*(\w+)", p).group(1).lower() for p in split_top(m.group(1)))
    return names


def externals(text):
    """Functions declared EXTERNAL (FILE_MGR, RTOVALUE): typed, but not variables."""
    names = set()
    for st in statements(text):
        m = re.match(r"external\s+(.*)", st, re.I)
        if m:
            names.update(p.strip().lower() for p in m.group(1).split(","))
    return names


def allocatables(text):
    names = set()
    for st in statements(text):
        m = re.match(r"\w[^:]*\ballocatable\b[^:]*::(.*)", st, re.I)
        if m:
            names.update(re.match(r"\s*(\w+)", p).group(1).lower() for p in split_top(m.group(1)))
    return names


def type_code(t, name):
    if t == "?":  # implicit typing (MODULE F_ has no IMPLICIT NONE)
        t = "integer" if name[0].lower() in "ijklmn" else "real"
    if t.startswith("character"):
        m = re.match(r"character\*(\d+)$", t)
        return f"S{m.group(1)}" if m else None
    if t.startswith("logical"):
        m = re.match(r"logical\*(\d)$", t)
        return f"i{m.group(1)}" if m else "i4"
    return {"real*8": "f8", "doubleprecision": "f8", "real*4": "f4", "real": "f4",
            "integer*1": "i1", "integer*2": "i2", "integer*4": "i4", "integer*8": "i8", "integer": "i4"}.get(t)


def dump_line(fname, name, t, rank, alloc):
    code = type_code(t, name)
    if code is None:
        return None
    lb, ub = (f"lbound({name})", f"ubound({name})") if rank else ("0", "0")
    sub = "odump_c" if code.startswith("S") else "odump"
    call = f"call {sub}(tag, '{fname}', CURIYR, {name}, sizeof({name}), '{code}', {rank}, {lb}, {ub})"
    return f"      if (allocated({name})) {call}" if alloc else f"      {call}"


def nested(names, inc_dir, seen=None):
    """Include files in order, with the ones they include (apq -> qblk, ampblk)."""
    seen = [] if seen is None else seen
    for n in names:
        n = n.lower()
        if n not in seen:
            seen.append(n)
            text = (inc_dir / n).read_text(encoding="latin-1")
            nested(re.findall(r"^\s*include\s*'(\w+)'", text, re.I | re.M), inc_dir, seen)
    return seen


def routines(build):
    """{routine name: code text} across the three sources."""
    out = {}
    for f in ("tran.f90", "tranfrt.f90", "tranair.f90"):
        text = code_only((build / f).read_text(encoding="latin-1"))
        starts = [(m.start(), m.group(2).lower()) for m in START.finditer(text)]
        for k, (pos, name) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else len(text)
            out.setdefault(name, text[pos:end])
    return out


def reach(name, bodies):
    """Identifiers used by a routine and everything it calls."""
    seen, todo, idents = set(), [name], set()
    while todo:
        r = todo.pop()
        if r in seen or r not in bodies:
            continue
        seen.add(r)
        words = {w.lower() for w in re.findall(r"\b[A-Za-z_]\w*\b", bodies[r])}
        idents |= words
        todo.extend(w for w in words if w in bodies and w not in seen)
    return idents


def write_state(inc_dir, build):
    # COMMON variables visible to the module.
    cdecls, cnames = {}, []
    for n in nested(COMMON_INCLUDES, inc_dir):
        txt = (inc_dir / n).read_text(encoding="latin-1")
        cdecls.update(declarations(txt))
        cnames += common_names(txt)
    cnames = list(dict.fromkeys(n.lower() for n in cnames))
    # Each module's own variables.
    mods = []
    for mod, src, prefix in MODULES:
        body = normalise(module_body((build / src).read_text(encoding="latin-1"), mod))
        d = declarations(body)
        skip = parameters(body) | set(cnames) | externals(body)
        own = {k: v for k, v in d.items() if k not in skip}
        mods.append((mod, prefix, own, allocatables(body)))

    bodies = routines(build)
    years = ", ".join(map(str, DUMP_YEARS))
    inc_c = "\n".join(f"      include '{n}'" for n in COMMON_INCLUDES)
    parts, counts = [], {}
    for tag, _, _, routine in TARGETS:
        used = reach(routine, bodies)
        subs = [f"      subroutine ost_{tag}(tag)\n      include 'parametr'\n      include 'ncntrl'\n"
                f"      character(*) tag\n      if (CURITR .ne. 1 .or. .not. any((/ {years} /) == CURIYR)) return"]
        n_total = 0
        for mod, prefix, own, alloc in mods:
            names = sorted(k for k in own if k in used)
            lines = [l for l in (dump_line(prefix + k, k, *own[k], k in alloc) for k in names) if l]
            if not lines:
                continue
            n_total += len(lines)
            only = ", ".join(names)
            subs.append(f"      call ost_{tag}_{mod.lower()}(tag)")
            parts.append(f"      subroutine ost_{tag}_{mod.lower()}(tag)\n      use {mod}, only: CURIYR, {only}\n"
                         f"      character(*) tag\n" + "\n".join(lines) + f"\n      end subroutine ost_{tag}_{mod.lower()}\n")
        cl = [l for l in (dump_line(k, k, *cdecls.get(k, ("?", 0)), False) for k in cnames if k in used) if l]
        if cl:
            n_total += len(cl)
            subs.append(f"      call ost_{tag}_c(tag)")
            parts.append(f"      subroutine ost_{tag}_c(tag)\n{inc_c}\n      character(*) tag\n"
                         + "\n".join(cl) + f"\n      end subroutine ost_{tag}_c\n")
        for alt in ALT_INCLUDES:
            txt = (inc_dir / alt).read_text(encoding="latin-1")
            adecls = declarations(txt)
            al = [l for l in (dump_line(f"{alt}__{k.lower()}", k, *adecls.get(k.lower(), ("?", 0)), False)
                              for k in dict.fromkeys(common_names(txt)) if k.lower() in used) if l]
            if al:
                n_total += len(al)
                subs.append(f"      call ost_{tag}_{alt}(tag)")
                parts.append(f"      subroutine ost_{tag}_{alt}(tag)\n      include 'parametr'\n      include 'ncntrl'\n"
                             f"      include '{alt}'\n      character(*) tag\n"
                             + "\n".join(al) + f"\n      end subroutine ost_{tag}_{alt}\n")
        parts.append("\n".join(subs) + f"\n      end subroutine ost_{tag}\n")
        counts[tag] = n_total

    # Final dump of the shared output blocks.
    fdecls, fnames = {}, []
    for n in FINAL_FILES + ["parametr"]:
        fdecls.update(declarations((inc_dir / n).read_text(encoding="latin-1")))
    for n in FINAL_FILES:
        fnames += common_names((inc_dir / n).read_text(encoding="latin-1"))
    fl = [l for l in (dump_line(n.lower(), n, *fdecls.get(n.lower(), ("?", 0)), False)
                      for n in dict.fromkeys(fnames)) if l]
    fl = [l.replace("(tag,", "('final',").replace("CURIYR", "0") for l in fl]
    inc_f = "\n".join(f"      include '{n}'" for n in FINAL_INCLUDES)
    (build / "oracle_state_tran.f90").write_text(f"""! Generated by hooks_tran.py. Do not edit.
      subroutine oracle_zero
{inc_f}
      end subroutine oracle_zero

      subroutine oracle_final
{inc_f}
{chr(10).join(fl)}
      end subroutine oracle_final

{chr(10).join(parts)}
""", encoding="latin-1")
    return counts


def instrument_private(build):
    """Dump each routine's saved local arrays at its end, into <tag>_out as p_<name>.

    These hold last year's values the routine reads back (with -fno-automatic, as in
    EIA's Intel build, every local is saved). Their year n-1 entries are the carried
    state a port needs; the year n entries are a check."""
    years = ", ".join(map(str, DUMP_YEARS))
    for tag, routine, names in ((t, r, ns) for t, rs in PRIVATE.items() for r, ns in rs.items()):
        for src in ("tran.f90", "tranfrt.f90", "tranair.f90"):
            p = build / src
            text = p.read_text(encoding="latin-1")
            m = re.search(rf"^\s*SUBROUTINE {routine}\b.*?^\s*END SUBROUTINE {routine}\b", text, re.I | re.M | re.S)
            if m:
                break
        else:
            raise SystemExit(f"hooks_tran: routine {routine} not found")
        body = m.group(0)
        decls = declarations(normalise(body))
        lines = [f"      IF (CURITR .EQ. 1 .AND. ANY((/ {years} /) == CURIYR)) THEN"]
        for k in names:
            t, rank = decls[k.lower()]
            lines.append(dump_line(f"p_{k.lower()}", k, t, rank, False).replace("(tag,", f"('{tag}_out',"))
        lines.append("      ENDIF")
        block = "\n".join(lines) + "\n"
        end = re.search(rf"^\s*END SUBROUTINE {routine}\b", body, re.I | re.M)
        ret = list(re.finditer(r"^\s*RETURN\s*$", body[:end.start()], re.I | re.M))
        tail = body[ret[-1].end():end.start()] if ret else ""
        at = ret[-1].start() if ret and not code_only(tail).strip() else end.start()
        at = body.rfind("\n", 0, at) + 1
        text = text[:m.start()] + body[:at] + block + body[at:] + text[m.end():]
        p.write_text(text, encoding="latin-1")


def instrument(build):
    instrument_private(build)
    for tag, src, call_re, _ in TARGETS:
        p = build / src
        text = p.read_text(encoding="latin-1")
        m = re.search(call_re, text, re.I | re.M)
        if not m:
            raise SystemExit(f"hooks_tran: call for {tag} not found in {src}")
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.index("\n", m.end())
        text = (text[:line_start] + f"    CALL OST_{tag.upper()}('{tag}_in')\n" + text[line_start:line_end + 1]
                + f"    CALL OST_{tag.upper()}('{tag}_out')\n" + text[line_end + 1:])
        p.write_text(text, encoding="latin-1")


def make_dirs():
    final = RUN / "out" / "state" / "final" / "0"
    final.mkdir(parents=True, exist_ok=True)
    for tag, *_ in TARGETS:
        for side in ("in", "out"):
            for y in DUMP_YEARS:
                d = RUN / "out" / "state" / f"{tag}_{side}" / str(y)
                d.mkdir(parents=True, exist_ok=True)
                for f in d.glob("*"):
                    f.unlink()
    for f in final.glob("*"):
        f.unlink()


if __name__ == "__main__":
    upstream, build = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    counts = write_state(upstream / "includes", build)
    instrument(build)
    make_dirs()
    print("hooks_tran: arrays per dump " + ", ".join(f"{t} {n}" for t, n in counts.items()))
