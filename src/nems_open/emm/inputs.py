"""One call that loads everything the electricity model reads.

    from nems_open.emm.inputs import load
    emm = load()
    emm.units.summer_mw, emm.shapes, emm.type_params["heat_rate"], ...
"""

from dataclasses import dataclass

import numpy as np

from nems_open.emm import history, load as load_mod, plants, regions, system, technology


@dataclass(frozen=True)
class EmmInputs:
    regions: tuple
    units: plants.Units
    shapes: np.ndarray                  # (25, 12, 3, 24) share of annual energy per typical hour
    day_weights: np.ndarray             # (12, 3)
    ecp_codes: tuple
    type_params: dict
    regional_costs: dict
    efd_types: tuple
    transmission: dict
    annual_controls: dict
    census_share: np.ndarray            # (28, 11, 4) share of each EMM region's load in each census division

    def existing_gw(self, year: int, efd_types=None, owners=None) -> np.ndarray:
        return plants.capacity_gw(year, efd_types, owners)

    history = staticmethod(lambda: history)


def load() -> EmmInputs:
    return EmmInputs(
        regions=regions.regions(), units=plants.load_units(),
        shapes=load_mod.regional_shapes(), day_weights=load_mod.day_weights(),
        ecp_codes=technology.ecp_codes(), type_params=technology.type_parameters(),
        regional_costs=technology.regional_costs(), efd_types=technology.efd_plant_types(),
        transmission=system.transmission(), annual_controls=system.annual_controls(),
        census_share=regions.emm_share_of_census(),
    )
