"""Shared pieces for the freight ports (tranfrt.f, MODULE F_).

Freight routines USE F_, so a Fortran name like ICAFE19 is the F_ variable, dumped
as "f_icafe19"; COMMON variables keep their names, and routines that include ANGTDM
see its prices ("angtdm__pgftrpv"). V(s) resolves a Fortran name the way the
compiler does for those routines, so a port can write V["icafe19"].
"""

from nems_open.transportation.common import f32

CAFE19 = 19
CAFE14 = 14
CAFE4 = 4
FUEL12 = 12
SC = 3
SC4 = 4
FLT, NFT = 2, 1  # fleet / non-fleet index
AGE = 34
NVMT = 11


# MODULE F_ PARAMETERs: constants in the Fortran, so not in the dumps.
PARAMS = dict(age=34, sec=18, sc=3, sc4=4, cafe4=4, cafe14=14, cafe19=19, ghgtry=5, fuel12=12, fnew=1, fstk=2,
              nft=1, flt=2, nvoc=1, voc=2, techp2=83, pbk_yr=7, cur=2, lag=1, nvmt=11, bsyr_vmt=34, bsyr_stk=2024)


class V:
    """Name resolver over the state dict for a freight routine."""

    def __init__(self, s: dict, angtdm: bool = True):
        self.s = s
        self.angtdm = angtdm
        self._keys = {}     # name -> state key, once the key is in the state

    def key(self, name: str) -> str:
        k = self._keys.get(name)
        if k is not None:
            return k
        low = name.lower()
        if "f_" + low in self.s:
            k = "f_" + low
        elif self.angtdm and "angtdm__" + low in self.s:
            k = "angtdm__" + low
        else:
            k = low
        if k in self.s:     # a name not in the state yet may resolve differently later
            self._keys[name] = k
        return k

    def __getitem__(self, name):
        k = self.key(name)
        s = self.s
        if k not in s and k in PARAMS:
            return PARAMS[k]
        return s[k]

    def __setitem__(self, name, value):
        self.s[self.key(name)] = value

    def __contains__(self, name):
        return self.key(name) in self.s

    def i(self, name) -> int:
        return int(self[name])

    def priv(self, name, make):
        """A saved local of a freight routine, kept across calls in the state dict."""
        k = "_frt_" + name
        if k not in self.s:
            self.s[k] = make()
        return self.s[k]


ONE = f32(1.0)
ZERO = f32(0.0)
