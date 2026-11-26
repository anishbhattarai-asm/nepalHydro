"""WECS/DHM methods: required inputs, warnings, provenance and formula shape."""

from __future__ import annotations

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
    with pytest.warns(HydroWarning, match="negative root") as record:
        fdc = wecs_dhm.flow_duration(c)
    assert fdc.points[100] == 0.0
    assert fdc.warnings == tuple(str(w.message) for w in record)
    assert record[0].filename == __file__
    # Between Q95 and a zero Q100 the curve falls back to linear interpolation.
    assert fdc.at(97.5) == pytest.approx(fdc.points[95] / 2)


# ------------------------------------------------------------ formula shape


def test_flood_fit_is_log_normal_through_the_anchors(solu_khola: Catchment) -> None:
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
    [((), ValueError), ((1,), ValueError), ((0.5, 2), ValueError), ("2", TypeError),
     (100, TypeError)],
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
