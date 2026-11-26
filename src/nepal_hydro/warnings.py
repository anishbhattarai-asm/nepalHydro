"""Warning classes, plus the one helper that emits them.

Every warning a calculation raises is also recorded on its result object, so
callers that silence Python warnings still see them in ``result.warnings``.
"""

from __future__ import annotations

import warnings as _warnings

__all__ = [
    "HydroWarning",
    "OutOfCalibrationRangeWarning",
    "UnverifiedCoefficientWarning",
    "emit",
]


class HydroWarning(UserWarning):
    """Base class for every nepal-hydro warning."""


class OutOfCalibrationRangeWarning(HydroWarning):
    """An input is valid but outside the range the method was calibrated on."""


class UnverifiedCoefficientWarning(HydroWarning):
    """A coefficient used in the calculation is not yet confirmed against the guideline."""


def emit(message: str, category: type[HydroWarning], stacklevel: int) -> str:
    """Issue ``message`` as a ``category`` warning and return it, for the result's list.

    ``stacklevel`` counts from the caller of ``emit``, as in :func:`warnings.warn`.
    """
    _warnings.warn(message, category, stacklevel=stacklevel + 1)
    return message
