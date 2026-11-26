"""Standard normal variate for flood frequency analysis."""

from __future__ import annotations

import math
from statistics import NormalDist

__all__ = ["standard_normal_variate"]

_STANDARD_NORMAL = NormalDist()


def standard_normal_variate(return_period_yr: float) -> float:
    """``S_T = Phi^-1(1 - 1/T)``, the standard normal variate for return period ``T``.

    Computed exactly rather than read from the guideline's Table A2, which the
    tests use as a fixture instead.
    """
    if isinstance(return_period_yr, bool) or not isinstance(return_period_yr, (int, float)):
        raise TypeError(f"return_period_yr must be a number, got {return_period_yr!r}")
    if not math.isfinite(return_period_yr) or return_period_yr <= 1:
        raise ValueError(f"return_period_yr must be a finite number > 1, got {return_period_yr!r}")
    return _STANDARD_NORMAL.inv_cdf(1.0 - 1.0 / return_period_yr)
