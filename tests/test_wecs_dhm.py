"""WECS/DHM methods: required inputs, warnings, provenance and formula shape."""

from __future__ import annotations

import itertools
import math
import warnings

import pytest

from nepal_hydro import (
    Catchment,
    FloodPeaks,
    FlowDurationCurve,
    HydroWarning,
    MissingInputError,
    MonthlyFlows,
    OutOfCalibrationRangeWarning,
    wecs_dhm,
)
from nepal_hydro._stats import standard_normal_variate
from nepal_hydro.coefficients import load_wecs_dhm

COEF = load_wecs_dhm()


# ------------------------------------------------------- only what is needed


def test_flood_peaks_needs_only_a3000() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        floods = wecs_dhm.flood_peaks(Catchment(area_below_3000_km2=97.7))
    assert round(floods[100].q_m3s) == 426


def test_flood_peaks_accepts_a3000_of_zero() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        floods = wecs_dhm.flood_peaks(Catchment(area_below_3000_km2=0))
    # (0 + 1) ** beta == 1, so Q2 and Q100 are the alphas.
    assert floods[2].q_m3s == pytest.approx(COEF.flood[2].alpha)
    assert floods[100].q_m3s == pytest.approx(COEF.flood[100].alpha)


def test_flood_peaks_missing_a3000() -> None:
    c = Catchment(area_km2=330, area_below_5000_km2=308.5, monsoon_wetness_index_mm=1500)
    with pytest.raises(MissingInputError, match="flood peaks") as info:
        wecs_dhm.flood_peaks(c)
    assert info.value.missing == ("area_below_3000_km2",)


def test_flow_duration_needs_a_a5000_and_mwi_only() -> None:
    c = Catchment(area_km2=330, area_below_5000_km2=308.5, monsoon_wetness_index_mm=1500)
    assert round(wecs_dhm.flow_duration(c).at(95), 2) == 2.03
    with pytest.raises(MissingInputError, match="flow duration") as info:
        wecs_dhm.flow_duration(Catchment(area_below_3000_km2=97.7))
    assert info.value.missing == ("area_km2", "area_below_5000_km2", "monsoon_wetness_index_mm")


def test_monthly_flows_needs_a_a5000_and_mwi_only() -> None:
    c = Catchment(area_km2=330, area_below_5000_km2=308.5, monsoon_wetness_index_mm=1500)
    assert round(wecs_dhm.monthly_flows(c)["Aug"], 2) == 52.45
    with pytest.raises(MissingInputError, match="monthly flows") as info:
        wecs_dhm.monthly_flows(Catchment(area_km2=330))
    assert info.value.missing == ("area_below_5000_km2", "monsoon_wetness_index_mm")


# ------------------------------------------------------------- provenance


def test_every_result_carries_method_source_and_warnings(solu_khola: Catchment) -> None:
    results: list[FloodPeaks | FlowDurationCurve | MonthlyFlows] = [
        wecs_dhm.flood_peaks(solu_khola),
        wecs_dhm.flow_duration(solu_khola),
        wecs_dhm.monthly_flows(solu_khola),
    ]
    sources = [COEF.flood_source, COEF.fdc_source, COEF.monthly_source]
    for result, source in zip(results, sources, strict=True):
        assert result.method == "WECS/DHM 1990"
        assert result.source == source
        assert "Civil Works Guidelines for Micro-Hydropower in Nepal" in result.source
        assert result.warnings == ()


# --------------------------------------------------------------- warnings


@pytest.mark.parametrize(
    "call", [wecs_dhm.flood_peaks, wecs_dhm.flow_duration, wecs_dhm.monthly_flows]
)
def test_out_of_calibration_total_area_warns_and_is_recorded(call: object) -> None:
    c = Catchment(
        area_km2=2, area_below_5000_km2=2, area_below_3000_km2=1, monsoon_wetness_index_mm=1500
    )
    with pytest.warns(OutOfCalibrationRangeWarning, match="area_km2 = 2 ") as record:
        result = call(c)  # type: ignore[operator]
    assert list(result.warnings) == [str(w.message) for w in record]
    assert len(result.warnings) == 1
    assert record[0].filename == __file__  # points at the caller's line


def test_large_a3000_without_total_area_warns() -> None:
    with pytest.warns(OutOfCalibrationRangeWarning, match="area_below_3000_km2"):
        floods = wecs_dhm.flood_peaks(Catchment(area_below_3000_km2=60000))
    assert len(floods.warnings) == 1


def test_warnings_are_recorded_even_when_silenced() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        floods = wecs_dhm.flood_peaks(Catchment(area_km2=1, area_below_3000_km2=0.5))
    assert len(floods.warnings) == 1


def test_q100_negative_root_is_zero_with_a_warning() -> None:
    q100 = COEF.fdc[100]
    # Smallest A5000 + 1 for which c + a * sqrt(x) >= 0:
    x_zero = (q100.c / q100.a) ** 2
    assert x_zero > 1  # so a tiny A5000 really does go negative
    c = Catchment(area_km2=10, area_below_5000_km2=0, monsoon_wetness_index_mm=1500)
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        fdc = wecs_dhm.flow_duration(c)
    assert fdc.points[100] == 0.0
    # This catchment is also all above 5000 m, so its curve is non-monotonic too.
    assert [w.category for w in record] == [HydroWarning, HydroWarning]
    assert "negative root" in str(record[0].message)
    assert "not monotonic" in str(record[1].message)
    assert fdc.warnings == tuple(str(w.message) for w in record)
    assert all(w.filename == __file__ for w in record)
    # Between Q95 and a zero Q100 the curve falls back to linear interpolation.
    assert fdc.at(97.5) == pytest.approx(fdc.points[95] / 2)


# ------------------------------------------------------------ formula shape


def test_flood_fit_is_log_normal_through_the_anchors(solu_khola: Catchment) -> None:
    with pytest.warns(HydroWarning, match="extrapolated"):
        floods = wecs_dhm.flood_peaks(solu_khola, return_periods=(2, 100, 1000, 2.5))
    q2, q100 = floods[2].q_m3s, floods[100].q_m3s
    sigma = math.log(q100 / q2) / standard_normal_variate(100)
    assert floods.sigma_ln == pytest.approx(sigma)
    for t in (1000, 2.5):
        expected = math.exp(math.log(q2) + standard_normal_variate(t) * sigma)
        assert floods[t].q_m3s == pytest.approx(expected)
    assert floods[2].q_m3s == COEF.flood[2].alpha * (97.7 + 1) ** COEF.flood[2].beta


def test_flood_keeps_requested_order_and_drops_duplicates(solu_khola: Catchment) -> None:
    floods = wecs_dhm.flood_peaks(solu_khola, return_periods=(100, 2, 100, 10))
    assert list(floods) == [100, 2, 10]


@pytest.mark.parametrize(
    ("periods", "error"),
    [((), ValueError), ((1,), ValueError), ((0.5, 2), ValueError), ((0, 2), ValueError),
     ((-5,), ValueError), ((10_000.5,), ValueError), ((2, 20_000), ValueError),
     ((float("nan"),), ValueError), ("2", TypeError), (100, TypeError), ((True,), TypeError)],
)  # fmt: skip
def test_flood_rejects_bad_return_periods(
    solu_khola: Catchment, periods: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        wecs_dhm.flood_peaks(solu_khola, return_periods=periods)  # type: ignore[arg-type]


def test_fdc_log_linear_form(solu_khola: Catchment) -> None:
    fdc = wecs_dhm.flow_duration(solu_khola)
    e = COEF.fdc[20]
    expected = math.exp(e.c + e.a * math.log(330) + e.b * math.log(1500))  # type: ignore[union-attr]
    assert fdc.points[20] == pytest.approx(expected)


def test_no_rounding_inside_results(solu_khola: Catchment) -> None:
    fdc = wecs_dhm.flow_duration(solu_khola)
    monthly = wecs_dhm.monthly_flows(solu_khola)
    floods = wecs_dhm.flood_peaks(solu_khola)
    for value in (*fdc.points.values(), *monthly.to_list(), floods[100].q_m3s):
        assert value != round(value, 2)


# -------------------------------------------------------------- monotonicity


def test_non_monotonic_curve_warns_and_keeps_values() -> None:
    # Mostly above 5000 m: Q20-Q60 use A = 330, the rest A5000 = 50.
    c = Catchment(area_km2=330, area_below_5000_km2=50, monsoon_wetness_index_mm=1500)
    with pytest.warns(HydroWarning, match="not monotonic") as record:
        fdc = wecs_dhm.flow_duration(c)
    assert len(record) == 1
    message = str(record[0].message)
    assert fdc.warnings == (message,)
    assert record[0].filename == __file__
    assert fdc.points[20] > fdc.points[5]
    assert "Q20 = 32.62 > Q5 = 10.11" in message
    # Exactly the rising pairs are named; Q20 -> Q40 falls, so Q40 is not.
    rising = [
        (lo, hi) for lo, hi in itertools.pairwise(fdc.points) if fdc.points[hi] > fdc.points[lo]
    ]
    assert rising == [(5, 20)]
    assert "Q40 = " not in message
    # Values are unchanged: same formula as for Solu Khola's Q20.
    e = COEF.fdc[20]
    assert fdc.points[20] == pytest.approx(
        math.exp(e.c + e.a * math.log(330) + e.b * math.log(1500))  # type: ignore[union-attr]
    )


def test_monotonic_curve_is_silent(solu_khola: Catchment) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert wecs_dhm.flow_duration(solu_khola).warnings == ()


def test_docstring_documents_reconstructed_forms() -> None:
    doc = wecs_dhm.flow_duration.__doc__ or ""
    assert "Q80" in doc
    assert "Q100" in doc
    assert "reconstructed from the Solu Khola worked example" in doc


# ------------------------------------------------------ return-period limits


@pytest.mark.parametrize("t", [1, 0.999, 0, -1])
def test_return_period_at_or_below_one_is_a_plain_value_error(
    solu_khola: Catchment, t: float
) -> None:
    with pytest.raises(ValueError, match="> 1") as info:
        wecs_dhm.flood_peaks(solu_khola, return_periods=[t])
    assert type(info.value) is ValueError  # not statistics.StatisticsError


def test_return_period_above_10000_names_the_offenders(solu_khola: Catchment) -> None:
    with pytest.raises(ValueError, match="at most 10000 years, got 20000, 100000"):
        wecs_dhm.flood_peaks(solu_khola, return_periods=[100, 20_000, 100_000])


def test_return_period_10000_is_allowed_with_a_warning(solu_khola: Catchment) -> None:
    with pytest.warns(HydroWarning, match="extrapolated beyond the 2/100-yr anchors"):
        floods = wecs_dhm.flood_peaks(solu_khola, return_periods=[10_000])
    assert floods[10_000].q_m3s > 0


def test_extrapolation_warning_names_every_period_above_100(solu_khola: Catchment) -> None:
    with pytest.warns(HydroWarning) as record:
        floods = wecs_dhm.flood_peaks(solu_khola, return_periods=[2, 100, 200, 1000, 150.5])
    assert len(record) == 1
    message = str(record[0].message)
    assert "T = 200, 1000, 150.5 yr extrapolated beyond the 2/100-yr anchors" in message
    assert floods.warnings == (message,)
    assert record[0].filename == __file__


@pytest.mark.parametrize("periods", [(2, 5, 10, 20, 50, 100), (1.5, 99.9), (100,)])
def test_periods_up_to_100_are_silent(solu_khola: Catchment, periods: tuple[float, ...]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert wecs_dhm.flood_peaks(solu_khola, return_periods=periods).warnings == ()
