"""EMM's Electricity Finance and Pricing (EFP, uefp.f), ported routine by routine.

Checked against the EMM oracle, which runs EFP on stand-in dispatch results
(oracle/efd_standin.f90): the tests check each routine's arithmetic, not EIA's
final prices (SCOPE.md, "EFP oracle input stand-ins").
"""
