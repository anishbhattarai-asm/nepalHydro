"""WECS/DHM (1990) regional regressions for ungauged Nepali rivers.

Coefficients come from ``data/wecs_dhm_1990.json``; nothing numeric about the
method lives here except the shape of each formula. Each function requires
only the ``Catchment`` fields its formulas use (worked out from the coefficient
data) and raises :class:`~nepal_hydro.MissingInputError` for the rest.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from nepal_hydro._stats import standard_normal_variate
from nepal_hydro.catchment import Catchment, FloatField, SubArea
from nepal_hydro.coefficients import (
    MONTHS,
    FdcLogLinear,
    FdcSquaredSqrt,
    Variable,
    load_wecs_dhm,
)
from nepal_hydro.results import FloodEstimate, FloodPeaks, FlowDurationCurve, MonthlyFlows
from nepal_hydro.warnings import HydroWarning, emit

__all__ = ["DEFAULT_RETURN_PERIODS", "flood_peaks", "flow_duration", "monthly_flows"]

DEFAULT_RETURN_PERIODS: tuple[int, ...] = (2, 5, 10, 20, 50, 100)

# Formula variables as named in the data files -> (Catchment field, offset).
_VARIABLES: dict[Variable, tuple[SubArea | FloatField, float]] = {
    "A": ("area_km2", 0.0),
    "A5000+1": ("area_below_5000_km2", 1.0),
    "A3000+1": ("area_below_3000_km2", 1.0),
}
_MWI: FloatField = "monsoon_wetness_index_mm"
_FIELD_ORDER: tuple[FloatField, ...] = (
    "area_km2", "area_below_5000_km2", "area_below_3000_km2", _MWI,
)  # fmt: skip
_SUB_AREAS: tuple[SubArea, ...] = ("area_below_5000_km2", "area_below_3000_km2")


def _inputs(
    c: Catchment, label: str, needed: Iterable[FloatField]
) -> tuple[dict[str, float], list[str]]:
    """Require ``needed`` from ``c`` and run the calibration check for them.

    Returns the values by field name and the calibration warnings (emitted at
    the user's call site: two frames above this helper's caller's caller).
    """
    wanted = set(needed)
    names = [f for f in _FIELD_ORDER if f in wanted]
    values: dict[str, float] = dict(zip(names, c.require(label, *names), strict=True))
    subs = [f for f in _SUB_AREAS if f in wanted]
    warnings = c.check_calibration(label, subs, load_wecs_dhm().calibration_area_km2,
                                   stacklevel=3)  # fmt: skip
    return values, warnings


def _x(values: dict[str, float], variable: Variable) -> float:
    field, offset = _VARIABLES[variable]
    return values[field] + offset


def flood_peaks(
    catchment: Catchment, return_periods: Sequence[float] = DEFAULT_RETURN_PERIODS
) -> FloodPeaks:
    """Instantaneous flood peaks for each return period, in m³/s.

    Q2 and Q100 come from the area below 3000 m; any other return period
    follows the log-normal fit through those two anchors,
    ``ln Q_T = ln Q_lo + (S_T - S_lo) * sigma`` with
    ``sigma = (ln Q_hi - ln Q_lo) / (S_hi - S_lo)`` and ``S_T`` the standard
    normal variate. Needs only ``area_below_3000_km2``.
    """
    coef = load_wecs_dhm()
    label = f"{coef.method} flood peaks"
    if isinstance(return_periods, (str, bytes)) or not isinstance(return_periods, Sequence):
        raise TypeError("return_periods must be a sequence of numbers")
    if not return_periods:
        raise ValueError("return_periods must not be empty")
    s_t = {t: standard_normal_variate(t) for t in return_periods}  # validates each T > 1

    anchors = [coef.flood[t] for t in sorted(coef.flood)]
    values, warnings = _inputs(catchment, label, (_VARIABLES[a.x][0] for a in anchors))
    lo, hi = anchors[0], anchors[-1]
    q_lo = lo.alpha * _x(values, lo.x) ** lo.beta
    q_hi = hi.alpha * _x(values, hi.x) ** hi.beta
    s_lo = standard_normal_variate(lo.return_period_yr)
    s_hi = standard_normal_variate(hi.return_period_yr)
    sigma_ln = (math.log(q_hi) - math.log(q_lo)) / (s_hi - s_lo)
    anchor_q: dict[float, float] = {lo.return_period_yr: q_lo, hi.return_period_yr: q_hi}

    estimates = {}
    for t, s in s_t.items():
        q = anchor_q.get(t)
        if q is None:
            q = math.exp(math.log(q_lo) + (s - s_lo) * sigma_ln)
        estimate = FloodEstimate(t, q)
        estimates[estimate.return_period_yr] = estimate
    return FloodPeaks(
        estimates=estimates,
        sigma_ln=sigma_ln,
        method=coef.method,
        source=coef.flood_source,
        warnings=tuple(warnings),
    )


def flow_duration(catchment: Catchment) -> FlowDurationCurve:
    """The flow duration curve at the guideline's points (Q0 ... Q100), in m³/s.

    Needs ``area_km2``, ``area_below_5000_km2`` and ``monsoon_wetness_index_mm``
    (the fields the curve's formulas use). Use :meth:`FlowDurationCurve.at`
    for exceedances between those points.
    """
    coef = load_wecs_dhm()
    label = f"{coef.method} flow duration"
    needed: list[FloatField] = []
    for entry in coef.fdc.values():
        needed.append(_VARIABLES[entry.x][0])
        if isinstance(entry, FdcLogLinear) and entry.b != 0:
            needed.append(_MWI)
    values, warnings = _inputs(catchment, label, needed)

    points: dict[int, float] = {}
    for p, entry in coef.fdc.items():
        x = _x(values, entry.x)
        if isinstance(entry, FdcLogLinear):
            ln_q = entry.c + entry.a * math.log(x)
            if entry.b != 0:
                ln_q += entry.b * math.log(values[_MWI])
            points[p] = math.exp(ln_q)
        else:
            assert isinstance(entry, FdcSquaredSqrt)
            root = entry.c + entry.a * math.sqrt(x)
            if root < 0:
                # Squaring a negative root would invent a flow; the form has no meaning here.
                warnings.append(
                    emit(
                        f"{label}: the Q{p} formula gives a negative root for "
                        f"{entry.x} = {x:g}; Q{p} is set to 0",
                        HydroWarning,
                        stacklevel=2,
                    )
                )
                root = 0.0
            points[p] = root**2
    return FlowDurationCurve(
        points=points, method=coef.method, source=coef.fdc_source, warnings=tuple(warnings)
    )


def monthly_flows(catchment: Catchment) -> MonthlyFlows:
    """Long-term mean flow for each month, ``C * A^a1 * (A5000+1)^a2 * MWI^a3``, in m³/s.

    A zero exponent drops its term. Needs the fields the monthly formulas use:
    ``area_km2``, ``area_below_5000_km2`` and ``monsoon_wetness_index_mm``.
    """
    coef = load_wecs_dhm()
    label = f"{coef.method} monthly flows"
    rows = [coef.monthly[m] for m in MONTHS]
    exponents: dict[FloatField, list[float]] = {
        "area_km2": [r.a1 for r in rows],
        "area_below_5000_km2": [r.a2 for r in rows],
        _MWI: [r.a3 for r in rows],
    }
    needed = [field for field, exps in exponents.items() if any(exps)]
    values, warnings = _inputs(catchment, label, needed)

    flows: dict[str, float] = {}
    for r in rows:
        q = r.c
        if r.a1:
            q *= values["area_km2"] ** r.a1
        if r.a2:
            q *= (values["area_below_5000_km2"] + 1.0) ** r.a2
        if r.a3:
            q *= values[_MWI] ** r.a3
        flows[r.month] = q
    return MonthlyFlows(
        values=flows, method=coef.method, source=coef.monthly_source, warnings=tuple(warnings)
    )
