"""Result types: interpolation, immutability, exports and round-trips."""

from __future__ import annotations

import io
import itertools
import json
import math
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from nepal_hydro import (
    Catchment,
    FloodEstimate,
    FloodPeaks,
    FlowDurationCurve,
    MonthlyFlows,
    result_from_dict,
    wecs_dhm,
)
from nepal_hydro.coefficients import MONTHS

META: dict[str, Any] = {"method": "test", "source": "test source"}


def _fdc(points: dict[int, float], **meta: Any) -> FlowDurationCurve:
    return FlowDurationCurve(points=points, **{**META, **meta})


# ------------------------------------------------------------ FDC.at()


def test_at_interpolates_in_log_flow() -> None:
    fdc = _fdc({0: 100.0, 20: 10.0, 100: 1.0})
    assert fdc.at(10) == pytest.approx(math.sqrt(100 * 10))  # geometric mean halfway
    assert fdc.at(60) == pytest.approx(math.sqrt(10 * 1))
    assert fdc.at(5) == pytest.approx(math.exp(math.log(100) + 0.25 * math.log(10 / 100)))


def test_at_returns_table_points_exactly(solu_khola: Catchment) -> None:
    fdc = wecs_dhm.flow_duration(solu_khola)
    for p, q in fdc.points.items():
        assert fdc.at(p) == q
    assert fdc.at(95.0) == fdc.points[95]


def test_at_is_monotone_between_points(solu_khola: Catchment) -> None:
    fdc = wecs_dhm.flow_duration(solu_khola)
    flows = [fdc.at(p / 2) for p in range(201)]
    assert all(a >= b for a, b in itertools.pairwise(flows))


@pytest.mark.parametrize("p", [-0.001, 100.001, -5, 150, math.inf, -math.inf])
def test_at_raises_outside_0_to_100(solu_khola: Catchment, p: float) -> None:
    with pytest.raises(ValueError, match=r"within 0\.\.100"):
        wecs_dhm.flow_duration(solu_khola).at(p)


def test_at_never_extrapolates_past_the_table() -> None:
    fdc = _fdc({5: 50.0, 95: 2.0})
    with pytest.raises(ValueError, match="never extrapolated"):
        fdc.at(2)
    with pytest.raises(ValueError, match="never extrapolated"):
        fdc.at(99)


@pytest.mark.parametrize(("p", "error"), [(math.nan, ValueError), ("50", TypeError),
                                          (True, TypeError)])  # fmt: skip
def test_at_rejects_non_numbers(p: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        _fdc({0: 2.0, 100: 1.0}).at(p)


def test_at_single_point_curve() -> None:
    assert _fdc({50: 3.0}).at(50) == 3.0


def test_fdc_points_are_sorted_and_validated() -> None:
    assert list(_fdc({100: 1.0, 0: 9.0, 50: 3.0}).points) == [0, 50, 100]
    with pytest.raises(ValueError, match="integer percent"):
        _fdc({101: 1.0})
    with pytest.raises(ValueError, match="integer percent"):
        _fdc({True: 1.0})
    with pytest.raises(ValueError, match="flow >= 0"):
        _fdc({0: -1.0})
    with pytest.raises(ValueError, match="at least one"):
        _fdc({})


# ------------------------------------------------------ construction rules


def test_results_are_frozen(solu_khola: Catchment) -> None:
    fdc = wecs_dhm.flow_duration(solu_khola)
    with pytest.raises(AttributeError):
        fdc.method = "x"  # type: ignore[misc]
    with pytest.raises(TypeError):
        fdc.points[5] = 1.0  # type: ignore[index]
    monthly = wecs_dhm.monthly_flows(solu_khola)
    with pytest.raises(TypeError):
        monthly.values["Jan"] = 1.0  # type: ignore[index]


def test_warnings_become_a_tuple() -> None:
    fdc = _fdc({0: 1.0}, warnings=["a", "b"])
    assert fdc.warnings == ("a", "b")


@pytest.mark.parametrize(
    ("meta", "error"),
    [({"method": ""}, ValueError), ({"source": " "}, ValueError), ({"warnings": [1]}, TypeError)],
)
def test_metadata_is_validated(meta: dict[str, Any], error: type[Exception]) -> None:
    with pytest.raises(error):
        _fdc({0: 1.0}, **meta)


def test_monthly_needs_all_twelve_months() -> None:
    with pytest.raises(ValueError, match="exactly the months"):
        MonthlyFlows(values={"Jan": 1.0}, **META)


def test_monthly_reads_like_a_mapping(solu_khola: Catchment) -> None:
    monthly = wecs_dhm.monthly_flows(solu_khola)
    assert list(monthly) == list(MONTHS) == list(monthly.keys())
    assert len(monthly) == 12
    assert "Jul" in monthly
    assert "July" not in monthly
    assert dict(monthly.items()) == dict(monthly.values)
    assert monthly.to_list() == [monthly[m] for m in MONTHS]
    assert monthly.annual_mean == pytest.approx(sum(monthly.to_list()) / 12)


def test_monthly_orders_months_whatever_the_input_order() -> None:
    values = {m: float(i) for i, m in enumerate(reversed(MONTHS))}
    assert list(MonthlyFlows(values=values, **META)) == list(MONTHS)


def test_flood_peaks_is_a_mapping(solu_khola: Catchment) -> None:
    floods = wecs_dhm.flood_peaks(solu_khola)
    assert list(floods) == [2, 5, 10, 20, 50, 100]
    assert len(floods) == 6
    assert 100 in floods
    assert floods.get(7) is None
    assert isinstance(floods[100], FloodEstimate)


def test_flood_peaks_validation() -> None:
    est = FloodEstimate(5, 10.0)
    with pytest.raises(ValueError, match="FloodEstimate for that T"):
        FloodPeaks(estimates={10: est}, sigma_ln=0.5, **META)
    with pytest.raises(ValueError, match="at least one"):
        FloodPeaks(estimates={}, sigma_ln=0.5, **META)
    with pytest.raises(ValueError, match="> 1"):
        FloodEstimate(1, 10.0)
    with pytest.raises(ValueError, match="flow >= 0"):
        FloodEstimate(5, math.inf)


def test_flood_estimate_normalises_integral_periods() -> None:
    np = pytest.importorskip("numpy")
    est = FloodEstimate(np.int64(50), np.float64(12.5))
    assert type(est.return_period_yr) is int
    assert type(est.q_m3s) is float


# ------------------------------------------------------------------- repr


def test_repr_rounds_but_values_do_not(solu_khola: Catchment) -> None:
    floods = wecs_dhm.flood_peaks(solu_khola)
    assert "Q100=426.06" in repr(floods)
    assert floods[100].q_m3s != 426.06
    assert "Q95=2.03" in repr(wecs_dhm.flow_duration(solu_khola))
    monthly = repr(wecs_dhm.monthly_flows(solu_khola))
    assert "Jul=43.86" in monthly
    assert "mean=16.68" in monthly
    assert "0 warnings" in monthly
    assert "1 warning)" in repr(_fdc({0: 1.0}, warnings=["x"]))
    assert repr(FloodEstimate(2, 105.931)) == "FloodEstimate(return_period_yr=2, q_m3s=105.93)"


# ---------------------------------------------------------------- exports


@pytest.fixture
def all_results(solu_khola: Catchment) -> list[FloodPeaks | FlowDurationCurve | MonthlyFlows]:
    return [
        wecs_dhm.flood_peaks(solu_khola, return_periods=(2, 2.33, 100)),
        wecs_dhm.flow_duration(solu_khola),
        wecs_dhm.monthly_flows(solu_khola),
    ]


def test_dict_and_json_round_trip_at_full_precision(
    all_results: list[FloodPeaks | FlowDurationCurve | MonthlyFlows],
) -> None:
    for result in all_results:
        data = result.to_dict()
        assert data["method"] == result.method
        assert data["source"] == result.source
        assert data["warnings"] == list(result.warnings)
        assert type(result).from_dict(data) == result
        assert result_from_dict(json.loads(result.to_json())) == result


def test_round_trip_keeps_warnings() -> None:
    fdc = _fdc({0: 2.0, 100: 1.0}, warnings=["careful"])
    assert FlowDurationCurve.from_dict(fdc.to_dict()).warnings == ("careful",)


def test_json_rounds_only_when_asked(solu_khola: Catchment) -> None:
    monthly = wecs_dhm.monthly_flows(solu_khola)
    full = json.loads(monthly.to_json())
    assert full["values"]["Jul"] == monthly["Jul"]
    short = json.loads(monthly.to_json(decimals=2, indent=None))
    assert short["values"]["Jul"] == 43.86
    assert short["annual_mean"] == 16.68
    assert short["method"] == "WECS/DHM 1990"


def test_from_dict_checks_the_type(solu_khola: Catchment) -> None:
    data = wecs_dhm.flow_duration(solu_khola).to_dict()
    with pytest.raises(ValueError, match="expected a MonthlyFlows"):
        MonthlyFlows.from_dict(data)
    with pytest.raises(ValueError, match="unknown result type"):
        result_from_dict({"type": "Nope"})


def test_csv_text_path_and_buffer(solu_khola: Catchment, tmp_path: Path) -> None:
    fdc = wecs_dhm.flow_duration(solu_khola)
    text = fdc.to_csv()
    assert text is not None
    lines = text.splitlines()
    assert lines[0] == "exceedance_pct,q_m3s"
    assert lines[1] == f"0,{fdc.points[0]!r}"
    assert len(lines) == 1 + len(fdc.points)

    path = tmp_path / "fdc.csv"
    assert fdc.to_csv(path) is None
    assert path.read_text(encoding="utf-8") == text
    fdc.to_csv(str(tmp_path / "again.csv"))
    assert (tmp_path / "again.csv").read_text(encoding="utf-8") == text

    buffer = io.StringIO()
    fdc.to_csv(buffer, decimals=2)
    assert buffer.getvalue().splitlines()[-1] == "100,1.78"


def test_csv_headers(all_results: list[FloodPeaks | FlowDurationCurve | MonthlyFlows]) -> None:
    headers = [r.to_csv().splitlines()[0] for r in all_results]  # type: ignore[union-attr]
    assert headers == ["return_period_yr,q_m3s", "exceedance_pct,q_m3s", "month,q_m3s"]


def test_to_dataframe_without_pandas(
    solu_khola: Catchment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pandas", None)
    with pytest.raises(ImportError, match="pip install pandas"):
        wecs_dhm.monthly_flows(solu_khola).to_dataframe()


def test_to_dataframe_builds_the_rows(
    solu_khola: Catchment, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeFrame:
        def __init__(self, rows: list[tuple[Any, float]], columns: list[str]) -> None:
            self.rows, self.columns = rows, columns
            self.attrs: dict[str, Any] = {}

    monkeypatch.setitem(sys.modules, "pandas", types.SimpleNamespace(DataFrame=FakeFrame))
    frame = wecs_dhm.monthly_flows(solu_khola).to_dataframe()
    assert frame.columns == ["month", "q_m3s"]
    assert frame.rows[6][0] == "Jul"
    assert frame.attrs["method"] == "WECS/DHM 1990"


def test_to_dataframe_with_real_pandas(solu_khola: Catchment) -> None:
    pytest.importorskip("pandas")
    frame = wecs_dhm.flow_duration(solu_khola).to_dataframe()
    assert list(frame.columns) == ["exceedance_pct", "q_m3s"]
    assert len(frame) == 8
