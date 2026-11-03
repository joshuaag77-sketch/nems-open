"""Macro and price series the CMM takes from NEMS, read from the restart.

AIMMS indexes them by calendar year through MAP_mnumyr_yr (MNUMYR 1 = 1990) and MAP_mnumy3_yr
(MNUMY3 = year - 1986, so MC_JPGDP starts at 1987 = 1.0).
"""

from nems_open.snapshot import Snapshot


class Macro:
    def __init__(self, snapshot: Snapshot | None = None):
        self.s = snapshot or Snapshot()

    def jpgdp(self, year: int) -> float:
        """MC_JPGDP: GDP deflator, 1987 = 1."""
        return float(self.s["MACOUT/MC_JPGDP"][year - 1987])

    def series(self, name: str, year: int) -> float:
        """A MACOUT series by MNUMYR year (MC_RLRMCORPPUAA, MC_JECIWSP, MC_WPI10, MC_WPIIND05, MC_WPI14)."""
        return float(self.s[f"MACOUT/{name}"][year - 1990])

    def price(self, name: str, year: int, region: int = 11) -> float:
        """An MPBLK price in the given census division (11 = US), 1987$/MMBtu: PDSTR, PDSIN, PELIN."""
        return float(self.s[f"MPBLK/{name}"][region - 1, year - 1990])

    def deflate(self, year_from: int, year_to: int) -> float:
        return self.jpgdp(year_to) / self.jpgdp(year_from)
