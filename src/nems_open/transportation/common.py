"""Dimensions and helpers shared by the transportation ports (MODULE T_ in tran.f)."""

import numpy as np

f32 = np.float32

BASEYR = 1990
MNUMCR = 11      # 9 census divisions, California (10, filled elsewhere), US (11)
MNUMYR = 61
AGEGRP = 5       # licensed-driver age groups
MF = 2           # 1 male, 2 female
MAXVTYP = 2      # 1 car, 2 light truck
MAXOWNER = 5     # household, business, government, utility, taxi
MAXLDV = 16      # fuel/powertrain types
MAXAGE = 25
MAXHAV = 4
STOCKYR = 2024   # last year of census-division stock history
