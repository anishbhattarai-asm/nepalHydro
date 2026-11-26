"""compare_monthly: WECS vs MIP side by side."""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping
from typing import Any

import pytest

from nepal_hydro import (
    Catchment,
    ComparisonRow,
    MonthlyComparison,
    MonthlyFlows,
    compare_monthly,
    mip,
    result_from_dict,
    wecs_dhm,
)
from nepal_hydro.coefficients import MONTHS


@pytest.fixture
def table(solu_khola: Catchment) -> MonthlyComparison:
    hydro = mip.monthly_hydrograph(solu_khola, measured_q_m3s=2.8, month=4)
    return compare_monthly(wecs_dhm.monthly_flows(solu_khola), hydro)


def test_rows_are_month_wecs_mip_ratio(table: MonthlyComparison) -> None:
    assert isinstance(table, Mapping)
    assert list(table) == list(MONTHS)
    assert len(table) == 12
    jul = table["Jul"]
    assert isinstance(jul, ComparisonRow)
    assert jul.month == "Jul"
    assert jul.wecs_m3s == table.wecs["Jul"]
    assert jul.mip_m3s == table.mip["Jul"]
    assert jul.ratio_mip_over_wecs == pytest.approx(jul.mip_m3s / jul.wecs_m3s)


def test_annual_row(table: MonthlyComparison) -> None:
    annual = table.annual
    assert annual.month == "annual"
    assert annual.wecs_m3s == table.wecs.annual_mean
    assert annual.mip_m3s == table.mip.annual_mean
    assert round(annual.wecs_m3s, 2) == 16.68


def test_method_source_and_warnings(solu_khola: Catchment) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        hydro = mip.monthly_hydrograph(Catchment(mip_region=4), measured_q_m3s=2.8, month=7)
        wecs = wecs_dhm.monthly_flows(Catchment(
            area_km2=2, area_below_5000_km2=2, monsoon_wetness_index_mm=1500
        ))  # fmt: skip
    table = compare_monthly(wecs, hydro)
    assert table.method == "WECS/DHM 1990 vs MIP 1982"
    assert table.source == f"{wecs.source}; {hydro.source}"
    assert table.warnings == (*wecs.warnings, *hydro.warnings)
    assert len(table.warnings) == 3


def test_same_source_is_not_repeated(solu_khola: Catchment) -> None:
    flows = wecs_dhm.monthly_flows(solu_khola)
    assert compare_monthly(flows, flows).source == flows.source


def test_zero_wecs_flow_gives_no_ratio() -> None:
    zero = MonthlyFlows(by_month=dict.fromkeys(MONTHS, 0.0), method="a", source="s")
    one = MonthlyFlows(by_month=dict.fromkeys(MONTHS, 1.0), method="b", source="s")
    table = compare_monthly(zero, one)
    assert table["Jan"].ratio_mip_over_wecs is None
    assert table.annual.ratio_mip_over_wecs is None
    assert "mip/wecs=n/a" in repr(table)
    assert "mip/wecs=n/a" in repr(table["Jan"])


@pytest.mark.parametrize("bad", [{"Jan": 1.0}, None, "flows"])
def test_rejects_non_results(table: MonthlyComparison, bad: Any) -> None:
    with pytest.raises(TypeError, match="MonthlyFlows"):
        compare_monthly(table.wecs, bad)
    with pytest.raises(TypeError, match="MonthlyFlows"):
        compare_monthly(bad, table.mip)
    with pytest.raises(TypeError, match="MonthlyFlows"):
        MonthlyComparison(wecs=table.wecs, mip=bad, method="m", source="s")


def test_exports(table: MonthlyComparison) -> None:
    csv_text = table.to_csv(decimals=2)
    assert csv_text is not None
    lines = csv_text.splitlines()
    assert lines[0] == "month,wecs_m3s,mip_m3s,ratio_mip_over_wecs"
    assert lines[7] == "Jul,43.86,37.91,0.86"
    assert lines[-1].startswith("annual,16.68,21.12,")
    assert len(lines) == 14
    data = json.loads(table.to_json())
    assert data["rows"][6] == {
        "month": "Jul", "wecs_m3s": table["Jul"].wecs_m3s,
        "mip_m3s": table["Jul"].mip_m3s,
        "ratio_mip_over_wecs": table["Jul"].ratio_mip_over_wecs,
    }  # fmt: skip
    assert result_from_dict(data) == table
    assert MonthlyComparison.from_dict(table.to_dict()) == table


def test_repr(table: MonthlyComparison) -> None:
    assert repr(table).startswith("MonthlyComparison(annual mean wecs=16.68, mip=21.12 m³/s")
    assert repr(table["Jul"]) == "ComparisonRow(Jul: wecs=43.86, mip=37.91 m³/s, mip/wecs=0.86)"


def test_ratio_direction_is_documented() -> None:
    assert "mip_m3s / wecs_m3s" in (ComparisonRow.__doc__ or "")
    assert "MIP divided by WECS" in (compare_monthly.__doc__ or "")
    assert "ratio_mip_over_wecs" in (MonthlyComparison.__doc__ or "")
