"""Shared pieces for the air ports (tranair.f, MODULE AIRMOD).

Air routines USE AIRMOD, dumped with prefix "a_"; the COMMON blocks it includes keep
their names. A(s) resolves a Fortran name the way the compiler does for them.
"""

from nems_open.transportation.common import f32

MAXATYP = 3
DOMINT = 2
DOM, INT = 1, 2
US, NUS = 1, 2
MAXWREG = 16
MAXACAGE = 48

# MODULE AIRMOD PARAMETERs: constants in the Fortran, so not in the dumps.
PARAMS = dict(maxatyp=3, domint=2, dom=1, int=2, us=1, nus=2, maxwreg=16, maxacage=48)

ONE = f32(1.0)
ZERO = f32(0.0)


class A:
    """Name resolver over the state dict for an air routine."""

    def __init__(self, s: dict):
        self.s = s

    def key(self, name: str) -> str:
        name = name.lower()
        return "a_" + name if "a_" + name in self.s else name

    def __getitem__(self, name):
        k = self.key(name)
        if k not in self.s and k in PARAMS:
            return PARAMS[k]
        return self.s[k]

    def __setitem__(self, name, value):
        self.s[self.key(name)] = value

    def __contains__(self, name):
        return self.key(name) in self.s

    def i(self, name) -> int:
        return int(self[name])
