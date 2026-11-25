"""SymPy in place of SymEngine for pyfrbus, where the compiled symengine package will not load.

pyfrbus uses symengine only to build its equations and differentiate them, for which it already falls back on SymPy
(pyfrbus.symbolic.take_symengine_partial). This offers the handful of names it uses, backed by SymPy, so no compiled
library is needed. Slower to set the model up; the solver's numeric work is the same.
"""

import sys
import types

import sympy


def symbols(names):
    if isinstance(names, str):
        return sympy.Symbol(names)
    return [sympy.Symbol(n) for n in names]


def install() -> bool:
    """Make `import symengine` work. True if the stand-in was used, False if the real package loads."""
    try:
        import symengine  # noqa: F401
        return False
    except ImportError:
        pass
    for name in [n for n in sys.modules if n == "symengine" or n.startswith("symengine.")]:
        del sys.modules[name]
    root, lib, wrapper = (types.ModuleType(n) for n in ("symengine", "symengine.lib", "symengine.lib.symengine_wrapper"))
    for name in ("log", "exp", "Max", "Min", "Abs", "Piecewise"):
        setattr(root, name, getattr(sympy, name))
    root.symbols, root.lib, lib.symengine_wrapper = symbols, lib, wrapper
    wrapper.Expr, wrapper.Symbol = sympy.Expr, sympy.Symbol
    sys.modules.update({"symengine": root, "symengine.lib": lib, "symengine.lib.symengine_wrapper": wrapper})
    return True
