"""Save the industrial stand-in's reference record (oil and gas mining and the process-flow industries, by region and
year, from the industrial oracle) as src/nems_open/industrial/reference.npz.

    NEMS_ORACLE_DIR=<cache> python scripts/pack_industrial_reference.py
"""

from nems_open import oracle_state
from nems_open.industrial.standin import Reference

final = oracle_state.load("wx_out", 61, "ind", only=["refqm", "refqi", "refqr", "refelown", "refelsale", "outind"])
ref = Reference.from_dump(final)
ref.save()
print("saved", ref.qm.shape)
