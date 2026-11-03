"""TRAN's first-call input readers, in the order the Fortran runs them.

TRAN (tran.f): READLDV, READVMT, READSTOCK, READHIST, READNHTSA on its first call;
TRANFRT's INIT: CFREAD, CFREADSTOCK; TRANAIR: READAIR. Each fills the state dict from
EIA's input files (NEMS_UPSTREAM/input/tdm); tests/test_tran_readers.py checks every
array against the oracle.
"""


def first_call(s: dict, traneff: int = 0) -> None:
    from nems_open.transportation.readers import air, freight, freight_stock, ldv, ldv_tables, nhtsa
    ldv.readldv(s, traneff=traneff)
    ldv_tables.readvmt(s)
    ldv_tables.readstock(s)
    ldv_tables.readhist(s)
    nhtsa.readnhtsa(s)
    freight.cfread(s, traneff=traneff)
    freight_stock.cfreadstock(s)
    air.readair(s)
