"""MIP (1982): a 12-month hydrograph from one dry-season flow measurement.

The method needs only the ``Catchment``'s ``mip_region``. Each region's
non-dimensional ordinates (April = 1.00, guideline Table A4) come from
``data/mip_1982.json``.

1. Add upstream abstractions to the measured flow.
2. Divide by the region's ordinate at the measurement date to get the
   expected mean April flow. With ``day`` set, that ordinate is interpolated
   between mid-month values (see :func:`ordinate_on`).
3. Multiply the April flow by each month's ordinate.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping
from itertools import accumulate

from nepal_hydro.catchment import Catchment
from nepal_hydro.coefficients import MONTHS, load_mip
from nepal_hydro.results import MonthlyFlows
from nepal_hydro.warnings import HydroWarning, UnverifiedCoefficientWarning, emit

__all__ = ["MONTH_DAYS", "monthly_hydrograph", "ordinate_on"]

# Calendar facts, not coefficients: a 365-day year (February has 28 days).
MONTH_DAYS: tuple[int, ...] = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_YEAR_DAYS = sum(MONTH_DAYS)
_MONTH_START: tuple[int, ...] = (0, *accumulate(MONTH_DAYS[:-1]))
_MID_MONTH: tuple[float, ...] = tuple(
    s + d / 2 for s, d in zip(_MONTH_START, MONTH_DAYS, strict=True)
)
_DRY_SEASON = frozenset({11, 12, 1, 2, 3, 4})  # Nov to Apr


def _month(month: object) -> int:
    if isinstance(month, bool) or not isinstance(month, numbers.Integral):
        raise TypeError(f"month must be an integer 1-12, got {month!r}")
    number = int(month)
    if not 1 <= number <= 12:
        raise ValueError(f"month must be 1-12, got {number}")
    return number


def _day(month: int, day: object) -> int | None:
    if day is None:
        return None
    if isinstance(day, bool) or not isinstance(day, numbers.Integral):
        raise TypeError(f"day must be an integer or None, got {day!r}")
    number = int(day)
    length = MONTH_DAYS[month - 1]
    if not 1 <= number <= length:
        raise ValueError(
            f"invalid date: {MONTHS[month - 1]} has {length} days, got day {day}"
            + (" (February is taken as 28 days)" if month == 2 and number == 29 else "")
        )
    return number


def _flow_arg(name: str, value: object, *, allow_zero: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a number, got {value!r}")
    number = float(value)
    ok = number >= 0 if allow_zero else number > 0
    if not math.isfinite(number) or not ok:
        raise ValueError(f"{name} must be a finite number {'>= 0' if allow_zero else '> 0'}, "
                         f"got {value!r}")  # fmt: skip
    return number


def ordinate_on(ordinates: Mapping[str, float], month: int, day: int | None = None) -> float:
    """The ordinate for a measurement in ``month`` (1-12) on ``day``.

    Without ``day`` it is that month's ordinate. With ``day`` each ordinate is
    taken as the value at the middle of its month, and the measurement date
    (the middle of that day, in a 365-day year) is interpolated linearly
    between the two mid-month points either side of it. December and January
    are neighbours, so Dec 31 and Jan 1 both interpolate between them.
    """
    m = _month(month)
    d = _day(m, day)
    i = m - 1
    if d is None:
        return ordinates[MONTHS[i]]
    t = _MONTH_START[i] + d - 0.5
    if t >= _MID_MONTH[i]:
        a, b = i, (i + 1) % 12
        mid_a, mid_b = _MID_MONTH[a], _MID_MONTH[b] + (_YEAR_DAYS if b == 0 else 0)
    else:
        a, b = (i - 1) % 12, i
        mid_a, mid_b = _MID_MONTH[a] - (_YEAR_DAYS if a == 11 else 0), _MID_MONTH[b]
    o_a, o_b = ordinates[MONTHS[a]], ordinates[MONTHS[b]]
    return o_a + (t - mid_a) / (mid_b - mid_a) * (o_b - o_a)


def monthly_hydrograph(
    catchment: Catchment,
    measured_q_m3s: float,
    month: int,
    day: int | None = None,
    abstractions_m3s: float = 0.0,
) -> MonthlyFlows:
    """Mean monthly flows from one measurement, by the MIP regional method, in m³/s.

    ``month`` is 1-12 and should be in the dry season (Nov-Apr); outside it the
    result is still computed, with a ``HydroWarning``. ``day`` (optional)
    interpolates the ordinate to the measurement date. ``abstractions_m3s`` is
    added to the measurement. Needs only ``catchment.mip_region``; regions not
    yet confirmed against the guideline emit ``UnverifiedCoefficientWarning``.
    """
    coef = load_mip()
    label = f"{coef.method} monthly hydrograph"
    region_no = catchment.require_mip_region(label)
    q_measured = _flow_arg("measured_q_m3s", measured_q_m3s, allow_zero=False)
    q_abstracted = _flow_arg("abstractions_m3s", abstractions_m3s, allow_zero=True)
    m = _month(month)
    region = coef.regions[region_no]
    ordinate = ordinate_on(region.ordinates, m, day)

    warnings: list[str] = []
    if not region.verified:
        warnings.append(
            emit(
                f"{label}: region {region_no} ordinates are not yet confirmed against the "
                f"guideline ({region.note})",
                UnverifiedCoefficientWarning,
                stacklevel=2,
            )
        )
    if m not in _DRY_SEASON:
        warnings.append(
            emit(
                f"{label}: the measurement is in {MONTHS[m - 1]}; MIP expects one taken "
                "between November and April with no recent heavy rain",
                HydroWarning,
                stacklevel=2,
            )
        )

    q_april = (q_measured + q_abstracted) / ordinate
    return MonthlyFlows(
        by_month={name: q_april * region.ordinates[name] for name in MONTHS},
        method=coef.method,
        source=coef.source,
        warnings=tuple(warnings),
    )
