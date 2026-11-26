"""MIP: argument rules, warnings, and date interpolation of the ordinates."""

from __future__ import annotations

import itertools
import warnings
from typing import Any

import pytest

from nepal_hydro import (
    Catchment,
    HydroWarning,
    MissingInputError,
    UnverifiedCoefficientWarning,
    mip,
)
from nepal_hydro.coefficients import MONTHS, load_mip
from nepal_hydro.methods.mip import MONTH_DAYS, ordinate_on

COEF = load_mip()
R3 = COEF.regions[3].ordinates


def _hydro(**kwargs: Any) -> Any:
    args: dict[str, Any] = {"measured_q_m3s": 2.8, "month": 4}
    args.update(kwargs)
    catchment = args.pop("catchment", Catchment(mip_region=3))
    return mip.monthly_hydrograph(catchment, **args)


@pytest.fixture(autouse=True)
def _strict() -> Any:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


# ------------------------------------------------------------ inputs needed


def test_needs_only_the_mip_region() -> None:
    hydro = _hydro(catchment=Catchment(mip_region=3))
    assert round(hydro["Aug"], 2) == 70.00
    assert hydro.method == "MIP 1982"
    assert hydro.source == COEF.source
    assert hydro.warnings == ()


def test_missing_region() -> None:
    with pytest.raises(MissingInputError, match="MIP 1982 monthly hydrograph") as info:
        _hydro(catchment=Catchment(area_km2=330))
    assert info.value.missing == ("mip_region",)


# ------------------------------------------------- the spec's argument table


@pytest.mark.parametrize("q", [0, -1, float("inf"), float("nan")])
def test_measured_q_must_be_positive(q: float) -> None:
    with pytest.raises(ValueError, match="measured_q_m3s"):
        _hydro(measured_q_m3s=q)


@pytest.mark.parametrize("month", [0, 13, -1])
def test_month_must_be_1_to_12(month: int) -> None:
    with pytest.raises(ValueError, match="month must be 1-12"):
        _hydro(month=month)


@pytest.mark.parametrize(("month", "day"), [(2, 30), (2, 0), (4, 31), (1, 0), (1, 32)])
def test_invalid_date(month: int, day: int) -> None:
    with pytest.raises(ValueError, match="invalid date"):
        _hydro(month=month, day=day)


def test_february_29_is_the_last_day_of_february() -> None:
    # Same position as Feb 28 in the 365-day interpolation.
    assert ordinate_on(R3, 2, 29) == ordinate_on(R3, 2, 28)
    assert _hydro(month=2, day=29).by_month == _hydro(month=2, day=28).by_month
    with pytest.raises(ValueError, match="Feb has 28 days, got day 30"):
        _hydro(month=2, day=30)


@pytest.mark.parametrize("a", [-0.1, float("inf")])
def test_abstractions_must_be_non_negative(a: float) -> None:
    with pytest.raises(ValueError, match="abstractions_m3s"):
        _hydro(abstractions_m3s=a)


@pytest.mark.parametrize(
    "kwargs",
    [{"measured_q_m3s": "2.8"}, {"month": 4.0}, {"month": True}, {"day": 15.0},
     {"day": True}, {"abstractions_m3s": None}],
)  # fmt: skip
def test_wrong_types(kwargs: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        _hydro(**kwargs)


def test_numpy_scalars() -> None:
    np = pytest.importorskip("numpy")
    hydro = _hydro(measured_q_m3s=np.float64(2.8), month=np.int64(4), day=np.int64(10))
    assert hydro["Apr"] > 0


def test_abstractions_are_added_to_the_measurement() -> None:
    assert _hydro(measured_q_m3s=2.0, abstractions_m3s=0.8).by_month == _hydro().by_month


@pytest.mark.parametrize("month", [11, 12, 1, 2, 3, 4])
def test_dry_season_months_are_silent(month: int) -> None:
    assert _hydro(month=month).warnings == ()


@pytest.mark.parametrize("month", [5, 6, 7, 8, 9, 10])
def test_month_outside_nov_apr_warns(month: int) -> None:
    with pytest.warns(HydroWarning, match="between November and April") as record:
        hydro = _hydro(month=month)
    assert hydro.warnings == (str(record[0].message),)
    assert MONTHS[month - 1] in hydro.warnings[0]
    assert record[0].filename == __file__
    # Still computed: April flow is the measurement over that month's ordinate.
    assert hydro["Apr"] == pytest.approx(2.8 / R3[MONTHS[month - 1]])


def test_region_4_warns_unverified() -> None:
    with pytest.warns(UnverifiedCoefficientWarning, match="region 4") as record:
        hydro = _hydro(catchment=Catchment(mip_region=4))
    assert len(record) == 1
    assert hydro.warnings == (str(record[0].message),)
    assert "6.89" in hydro.warnings[0]
    assert record[0].filename == __file__


@pytest.mark.parametrize("region", [1, 2, 3, 5, 6, 7])
def test_other_regions_are_silent(region: int) -> None:
    assert _hydro(catchment=Catchment(mip_region=region)).warnings == ()


def test_region_4_outside_dry_season_gives_both_warnings() -> None:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        hydro = _hydro(catchment=Catchment(mip_region=4), month=7)
    assert [w.category for w in record] == [UnverifiedCoefficientWarning, HydroWarning]
    assert len(hydro.warnings) == 2


# ----------------------------------------------------------- the hydrograph


@pytest.mark.parametrize("region", range(1, 8))
def test_hydrograph_is_april_flow_times_ordinates(region: int) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        hydro = _hydro(catchment=Catchment(mip_region=region), measured_q_m3s=3.0, month=1)
    ords = COEF.regions[region].ordinates
    q_april = 3.0 / ords["Jan"]
    for m in MONTHS:
        assert hydro[m] == pytest.approx(q_april * ords[m])
    assert hydro["Jan"] == pytest.approx(3.0)


def test_scales_linearly_with_the_measurement() -> None:
    one, three = (
        _hydro(measured_q_m3s=1.0, month=2, day=10),
        _hydro(measured_q_m3s=3.0, month=2, day=10),
    )
    for m in MONTHS:
        assert three[m] == pytest.approx(3 * one[m])


def test_no_day_uses_the_month_ordinate() -> None:
    for i, m in enumerate(MONTHS, start=1):
        assert ordinate_on(R3, i) == R3[m]


# ------------------------------------------------------- day interpolation


def test_mid_month_day_hits_the_ordinate_exactly() -> None:
    # In a 31-day month the middle of day 16 is the middle of the month.
    for i, m in enumerate(MONTHS, start=1):
        if MONTH_DAYS[i - 1] == 31:
            assert ordinate_on(R3, i, 16) == pytest.approx(R3[m])


def test_thirty_day_month_mid_falls_between_days_15_and_16() -> None:
    # Apr mid-month is t = 105.0; day 15 (t = 104.5) sits on the Mar-Apr segment
    # (mid Mar 74.5) and day 16 (t = 105.5) on the Apr-May segment (mid May 135.5).
    assert ordinate_on(R3, 4, 15) == pytest.approx(R3["Apr"] + 0.5 / 30.5 * (R3["Mar"] - R3["Apr"]))
    assert ordinate_on(R3, 4, 16) == pytest.approx(R3["Apr"] + 0.5 / 30.5 * (R3["May"] - R3["Apr"]))


def test_interpolation_is_linear_between_mid_months() -> None:
    # Jan 16 (mid Jan, t = 15.5) to Feb 14.5 (mid Feb, t = 45): Jan 31 is t = 30.5.
    expected = R3["Jan"] + (30.5 - 15.5) / (45.0 - 15.5) * (R3["Feb"] - R3["Jan"])
    assert ordinate_on(R3, 1, 31) == pytest.approx(expected)
    # Feb 1 (t = 31.5) uses the same Jan-Feb segment.
    expected = R3["Jan"] + (31.5 - 15.5) / (45.0 - 15.5) * (R3["Feb"] - R3["Jan"])
    assert ordinate_on(R3, 2, 1) == pytest.approx(expected)


def test_wraps_between_december_and_january() -> None:
    # Mid Dec is t = 349.5, mid Jan is t = 15.5 + 365 = 380.5: a 31-day segment.
    dec31 = ordinate_on(R3, 12, 31)  # t = 364.5
    jan1 = ordinate_on(R3, 1, 1)  # t = 0.5, i.e. 365.5
    step = (R3["Jan"] - R3["Dec"]) / 31
    assert dec31 == pytest.approx(R3["Dec"] + 15 * step)
    assert jan1 == pytest.approx(R3["Dec"] + 16 * step)
    assert jan1 - dec31 == pytest.approx(step)
    assert min(R3["Jan"], R3["Dec"]) < jan1 < dec31 < max(R3["Jan"], R3["Dec"])


def test_daily_ordinates_change_by_one_step_per_day_all_year() -> None:
    # Walk every day of the year: consecutive days never jump, including month ends.
    days = [(m, d) for m in range(1, 13) for d in range(1, MONTH_DAYS[m - 1] + 1)]
    values = [ordinate_on(R3, m, d) for m, d in days]
    values.append(values[0])  # Dec 31 -> Jan 1
    largest_step = max(abs(b - a) for a, b in itertools.pairwise(values))
    biggest_monthly_change = max(
        abs(R3[b] - R3[a]) for a, b in itertools.pairwise([*MONTHS, "Jan"])
    )
    assert largest_step <= biggest_monthly_change / 29.5 + 1e-12
    assert len(days) == 365


def test_feb_28_and_mar_1_are_neighbours() -> None:
    # Mid Feb t = 45, mid Mar t = 74.5; Feb 28 is t = 58.5, Mar 1 is t = 59.5.
    step = (R3["Mar"] - R3["Feb"]) / 29.5
    assert ordinate_on(R3, 3, 1) - ordinate_on(R3, 2, 28) == pytest.approx(step)


def test_day_changes_the_april_flow() -> None:
    # Measured early in April, the ordinate is pulled towards March's.
    hydro = _hydro(month=4, day=1)
    assert hydro["Apr"] == pytest.approx(2.8 / ordinate_on(R3, 4, 1))
    assert hydro["Apr"] != pytest.approx(2.8)
