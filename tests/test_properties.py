"""Property tests (hypothesis).

Inputs stay inside the WECS/DHM calibration range (total area 4 to 54 100 km²)
unless a test is about warnings. The guideline gives no MWI range; 100 to
6000 mm is used here as a plausible span for Nepal.
"""

from __future__ import annotations

import itertools
import math
import warnings
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nepal_hydro import (
    Catchment,
    FlowDurationCurve,
    HydroWarning,
    MonthlyFlows,
    UnverifiedCoefficientWarning,
    mip,
    wecs_dhm,
)
from nepal_hydro.coefficients import MONTHS, load_mip
from nepal_hydro.methods.mip import MONTH_DAYS

A_MIN, A_MAX = 4.0, 54100.0
MWI_MIN, MWI_MAX = 100.0, 6000.0
# Where the curve is monotonic inside the calibration range (mapped on a grid,
# then searched by hypothesis): mostly below 5000 m and not too dry.
MONO_A5000_FRACTION, MONO_MWI_MIN = 0.7, 1000.0

areas = st.floats(A_MIN, A_MAX)
mwis = st.floats(MWI_MIN, MWI_MAX)
fractions = st.floats(0.0, 1.0)


@st.composite
def catchments(
    draw: st.DrawFn, a5000_fraction: tuple[float, float] = (0.0, 1.0), mwi_min: float = MWI_MIN
) -> Catchment:
    """A full catchment inside the calibration range with consistent sub-areas."""
    a = draw(areas)
    a5000 = a * draw(st.floats(*a5000_fraction))
    a3000 = a5000 * draw(fractions)
    return Catchment(
        area_km2=a,
        area_below_5000_km2=a5000,
        area_below_3000_km2=a3000,
        monsoon_wetness_index_mm=draw(st.floats(mwi_min, MWI_MAX)),
    )


def _quietly(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call fn ignoring HydroWarnings (e.g. a non-monotonic curve) but nothing else."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", HydroWarning)
        return fn(*args, **kwargs)


def _rising_pairs(fdc: FlowDurationCurve) -> list[tuple[int, int]]:
    return [
        (lo, hi) for lo, hi in itertools.pairwise(fdc.points) if fdc.points[hi] > fdc.points[lo]
    ]


# ------------------------------------------------------- flow duration curve


@given(catchments(a5000_fraction=(MONO_A5000_FRACTION, 1.0), mwi_min=MONO_MWI_MIN))
def test_fdc_decreases_with_exceedance_on_monotonic_catchments(c: Catchment) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no warning of any kind on these catchments
        fdc = wecs_dhm.flow_duration(c)
    flows = list(fdc.points.values())
    assert all(b <= a for a, b in itertools.pairwise(flows))
    between = [fdc.at(p) for p in range(101)]
    assert all(b <= a for a, b in itertools.pairwise(between))


@given(
    a=areas,
    a5000_fraction=fractions,
    mwi=mwis,
)
def test_fdc_warns_if_and_only_if_the_curve_rises(
    a: float, a5000_fraction: float, mwi: float
) -> None:
    # About warnings, so the whole calibration range, including dry and high basins.
    c = Catchment(area_km2=a, area_below_5000_km2=a * a5000_fraction, monsoon_wetness_index_mm=mwi)
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        fdc = wecs_dhm.flow_duration(c)
    rising = _rising_pairs(fdc)
    emitted = [str(w.message) for w in record if "not monotonic" in str(w.message)]
    recorded = [m for m in fdc.warnings if "not monotonic" in m]
    assert emitted == recorded
    assert len(emitted) == (1 if rising else 0)
    for lo, hi in rising:
        assert f"Q{hi} = {fdc.points[hi]:.4g} > Q{lo} = {fdc.points[lo]:.4g}" in emitted[0]
    assert all(w.category is HydroWarning for w in record)


FDC_FIELDS = ("area_km2", "area_below_5000_km2", "monsoon_wetness_index_mm")


@st.composite
def one_field_varied(draw: st.DrawFn) -> tuple[str, Catchment, Catchment]:
    """A catchment, and the same catchment with one of A, A5000 or MWI made larger."""
    base = draw(catchments())
    field = draw(st.sampled_from(FDC_FIELDS))
    assert base.area_km2 is not None
    current: float = getattr(base, field)
    upper = {
        "area_km2": A_MAX,  # A may grow up to the range end
        "area_below_5000_km2": base.area_km2,  # A5000 may grow up to A
        "monsoon_wetness_index_mm": MWI_MAX,
    }[field]
    larger = draw(st.floats(current, upper))
    kwargs = {
        f: getattr(base, f)
        for f in (
            "area_km2",
            "area_below_5000_km2",
            "area_below_3000_km2",
            "monsoon_wetness_index_mm",
        )
    }
    kwargs[field] = larger
    return field, base, Catchment(**kwargs)


@given(one_field_varied())
def test_monthly_flows_never_fall_when_one_input_grows(
    case: tuple[str, Catchment, Catchment],
) -> None:
    field, small, large = case
    before: MonthlyFlows = _quietly(wecs_dhm.monthly_flows, small)
    after: MonthlyFlows = _quietly(wecs_dhm.monthly_flows, large)
    for month in MONTHS:
        assert after[month] >= before[month], (field, month)


@given(one_field_varied())
def test_fdc_never_falls_when_one_input_grows(case: tuple[str, Catchment, Catchment]) -> None:
    field, small, large = case
    before: FlowDurationCurve = _quietly(wecs_dhm.flow_duration, small)
    after: FlowDurationCurve = _quietly(wecs_dhm.flow_duration, large)
    for p in before.points:
        assert after.points[p] >= before.points[p], (field, p)


# --------------------------------------------------------------- flood peaks

return_periods = st.lists(
    st.floats(1.001, 10000.0).map(lambda t: round(t, 3)), min_size=2, max_size=12, unique=True
)


@given(a3000=st.floats(0.0, A_MAX), periods=return_periods)
def test_flood_strictly_increases_with_return_period(a3000: float, periods: list[float]) -> None:
    periods = sorted(t for t in periods if t > 1)
    floods = wecs_dhm.flood_peaks(Catchment(area_below_3000_km2=a3000), return_periods=periods)
    flows = [floods[t].q_m3s for t in periods]
    assert all(b > a for a, b in itertools.pairwise(flows))


@given(a3000=st.floats(0.0, A_MAX), grow=st.floats(0.0, A_MAX), t=st.floats(1.01, 10000.0))
def test_flood_never_falls_when_a3000_grows(a3000: float, grow: float, t: float) -> None:
    larger = min(a3000 + grow, A_MAX)
    small = wecs_dhm.flood_peaks(Catchment(area_below_3000_km2=a3000), return_periods=[t])
    large = wecs_dhm.flood_peaks(Catchment(area_below_3000_km2=larger), return_periods=[t])
    # ln Q_T = (1 - r) ln Q2 + r ln Q100 with r = S_T / S_100. Its slope in ln(A3000 + 1),
    # 0.8783 - 0.1441 r, is positive for any T in use, so Q_T grows with A3000. For T > 100
    # (r > 1) one term falls while the other rises, so a tiny growth can round one ulp the
    # wrong way: allow 1e-12 relative. (Monthly and FDC flows need no tolerance.)
    assert large[t].q_m3s >= small[t].q_m3s * (1 - 1e-12)


# ------------------------------------------------------------------------ MIP


@st.composite
def dry_season_dates(draw: st.DrawFn) -> tuple[int, int | None]:
    month = draw(st.sampled_from([11, 12, 1, 2, 3, 4]))
    last = 29 if month == 2 else MONTH_DAYS[month - 1]  # Feb 29 is accepted
    return month, draw(st.none() | st.integers(1, last))


flows_m3s = st.floats(1e-3, 1e3)
abstractions = st.floats(0.0, 1e2)
scales = st.floats(1e-3, 1e3)


def _hydro(region: int, q: float, a: float, date: tuple[int, int | None]) -> MonthlyFlows:
    month, day = date
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnverifiedCoefficientWarning)  # region 4
        return mip.monthly_hydrograph(
            Catchment(mip_region=region), measured_q_m3s=q, month=month, day=day,
            abstractions_m3s=a,
        )  # fmt: skip


regions = st.integers(1, 7)


@given(regions, flows_m3s, abstractions, dry_season_dates(), scales)
def test_mip_is_homogeneous(
    region: int, q: float, a: float, date: tuple[int, int | None], k: float
) -> None:
    base = _hydro(region, q, a, date)
    scaled = _hydro(region, k * q, k * a, date)
    for m in MONTHS:
        assert scaled[m] == pytest.approx(k * base[m], rel=1e-12)


@given(regions, flows_m3s, flows_m3s, abstractions, abstractions, dry_season_dates())
def test_mip_is_additive(
    region: int, q1: float, q2: float, a1: float, a2: float, date: tuple[int, int | None]
) -> None:
    total = _hydro(region, q1 + q2, a1 + a2, date)
    one, two = _hydro(region, q1, a1, date), _hydro(region, q2, a2, date)
    for m in MONTHS:
        assert total[m] == pytest.approx(one[m] + two[m], rel=1e-12)


@given(regions, flows_m3s, abstractions, dry_season_dates())
def test_mip_abstractions_count_exactly_like_measured_flow(
    region: int, q: float, a: float, date: tuple[int, int | None]
) -> None:
    # Only the sum matters, bit for bit.
    assert _hydro(region, q, a, date).by_month == _hydro(region, q + a, 0.0, date).by_month


@given(regions, flows_m3s, dry_season_dates())
def test_mip_hydrograph_has_the_region_shape(
    region: int, q: float, date: tuple[int, int | None]
) -> None:
    hydro = _hydro(region, q, 0.0, date)
    assert all(math.isfinite(v) and v > 0 for v in hydro.values())
    ratio = hydro["Aug"] / hydro["Apr"]
    ords = load_mip().regions[region].ordinates
    assert ratio == pytest.approx(ords["Aug"] / ords["Apr"], rel=1e-12)
