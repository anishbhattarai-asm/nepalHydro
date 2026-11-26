"""nepal-hydro: WECS/DHM (1990) and MIP (1982) hydrology for ungauged rivers in Nepal.

Outputs are estimates. A licensed engineer must review them before anything is built.
"""

from nepal_hydro.catchment import Catchment, MissingInputError
from nepal_hydro.warnings import (
    HydroWarning,
    OutOfCalibrationRangeWarning,
    UnverifiedCoefficientWarning,
)

__version__ = "0.1.0.dev0"

__all__ = [
    "Catchment",
    "HydroWarning",
    "MissingInputError",
    "OutOfCalibrationRangeWarning",
    "UnverifiedCoefficientWarning",
    "__version__",
]
