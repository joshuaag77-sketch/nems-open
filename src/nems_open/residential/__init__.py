"""Residential demand: port of EIA's resd.f, routine by routine.

Every routine in resd.f is contained in SUBROUTINE RESD and works on shared
state (MODULE R_ and the RESDREP, RTEK, RSCON, RSEFF blocks). The ports do the
same: each takes a dict of FArrays keyed by lowercase Fortran name and updates
it in place, so a test can feed it the oracle's state before the routine and
compare with the state after.
"""
