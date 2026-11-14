"""Text changes that let EIA's AIMMS interface (uaimms.f, after patch_intel.py) run in the WSL oracle.

NEMS starts AIMMS with a Windows batch file that activates a Python environment and posts the year to a
web service (main\\call_p2_endpoint.bat -> p2_endpoint_run_api.py). Here the same call runs ./run_aimms.sh
(oracle/run_aimms.sh), which reads the year, iteration and module NEMS has just written to
main\\endpoint_p2_caller.txt and runs Windows aimms.exe on the oracle's wrapper project
(oracle/aimms_patch.py). Everything else in uaimms.f, including the files it writes for AIMMS and reads back,
is EIA's code unchanged.

Usage: python aimms_fortran.py uaimms.f90
"""

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="latin-1")
pat = re.compile(r"CALL EXECUTE_COMMAND_LINE\(trim\(cmd\),\s*wait=\.true\.,\s*CMDSTAT=iret\)", re.I)
text, n = pat.subn("CALL EXECUTE_COMMAND_LINE('bash ./run_aimms.sh', wait=.true., CMDSTAT=iret)", text)
if n == 0:
    raise SystemExit("aimms_fortran.py: no AIMMS launch found in " + str(path))
path.write_text(text, encoding="latin-1")
print(f"aimms_fortran.py: {n} AIMMS launch(es) pointed at run_aimms.sh")
