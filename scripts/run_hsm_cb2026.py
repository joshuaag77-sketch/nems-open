import sys, numpy as np
sys.path.insert(0, r"C:\Users\joshu\dev\nems-open-ogs\src")
from nems_open.ogsm import run_hsm
p = run_hsm.run()
ns = p.__getattr__("ogsmout")
np.savez(sys.argv[1], **{k: np.asarray(v) for k, v in vars(ns).items() if not k.startswith("_")})
