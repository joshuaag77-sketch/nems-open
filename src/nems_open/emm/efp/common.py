"""Helpers shared by the EFP routines. Same conventions as LDSM (emm/ldsm/common.py):
the state is a dict of FArrays and NumPy scalars keyed by lowercase Fortran name,
changed in place; float32 where the Fortran is REAL/REAL*4, float64 where REAL*8."""

from nems_open.emm.ldsm.common import f32, f64, i, put  # noqa: F401
from nems_open.residential.common import expf, logf, powf, powi  # noqa: F401
