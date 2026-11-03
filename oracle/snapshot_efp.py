"""Snapshot EFP's direct-access files (each region's books) during an EMM oracle run.

EFP keeps each region's books in scratch files (EMM_EFPR, EMM_EFPRC, EMM_EFPRCY,
EMM_EFPBLDS) and the build records in EMM_ECPIDAF. Only the latest state survives
a run, and the COMMON dumps cannot see them. Between the end of LDSM and the start
of EFP in a year, EFP's files hold exactly what EFP will read. So this watches for
LDSM's after-dump of a year to be complete, pauses the oracle, copies the files,
and resumes it. No change to the oracle build.

Usage (run_emm must be reset by gen_oracle first; start this, then the oracle):
    python -I snapshot_efp.py 32 41        # NEMS year indexes (2021, 2030)
Snapshots go to run_emm/efp_books/<year>/.
"""

import ctypes
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE / "run_emm"
FILES = ["EMM_EFPR.daf", "EMM_EFPRC.daf", "EMM_EFPRCY.daf", "EMM_EFPBLDS.daf", "EMM_ECPIDAF.daf"]
LDSM_ARRAYS = 205  # lines in ld_out's index when its dump is complete

ntdll = ctypes.WinDLL("ntdll")
kernel32 = ctypes.WinDLL("kernel32")
PROCESS_SUSPEND_RESUME = 0x0800


def oracle_pid():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_Process -Filter \"Name='oracle.exe'\" | Where-Object "
                          "{ $_.ExecutablePath -match 'nems-open-emm' }).ProcessId"],
                         capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None


def lines(p):
    try:
        return p.read_bytes().count(b"\n")
    except OSError:
        return 0


def main():
    years = [int(a) for a in sys.argv[1:]]
    for y in years:
        idx = RUN / "out" / "state" / "ld_out" / str(y) / "index.txt"
        while lines(idx) < LDSM_ARRAYS:
            time.sleep(0.05)
        pid = oracle_pid()
        h = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        ntdll.NtSuspendProcess(h)
        try:
            dest = RUN / "efp_books" / str(y)
            dest.mkdir(parents=True, exist_ok=True)
            for f in FILES:
                shutil.copyfile(RUN / f, dest / f)
            print(f"year {y}: copied {', '.join(FILES)}", flush=True)
        finally:
            ntdll.NtResumeProcess(h)
            kernel32.CloseHandle(h)


if __name__ == "__main__":
    main()
