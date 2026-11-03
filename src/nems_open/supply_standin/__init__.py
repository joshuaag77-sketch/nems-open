"""Temporary reduced-form supply side, fitted to EIA's AEO2026 cases.

Stands in for the electricity, gas, oil, refining and coal modules until they are
ported. See docs/supply_standin.md.
"""

from nems_open.supply_standin.model import Result, SupplyStandin

__all__ = ["Result", "SupplyStandin"]
