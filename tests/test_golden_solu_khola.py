"""Release gate: the guideline's Solu Khola worked example, at its own rounding.

Golden values and tolerances come from docs/ARCHITECTURE.md ("Testing
strategy"). Never edit them to make a test pass.
"""

from __future__ import annotations

import warnings

import pytest

from nepal_hydro import Catchment, compare_monthly, mip, wecs_dhm
from nepal_hydro.coefficients import MONTHS

FLOOD_GOLDEN = {2: 106, 5: 175, 10: 228, 20: 283, 50: 362, 100: 426}  # round to integer
FDC_GOLDEN = {
    0: 98.45, 5: 59.33, 20: 32.62, 40: 9.47, 60: 4.58, 80: 3.00, 95: 2.03, 100: 1.78,
}  # round to 2 dp  # fmt: skip
WECS_MONTHLY_GOLDEN = [
    3.88, 3.30, 3.00, 3.17, 4.37, 15.17, 43.86, 52.45, 40.07, 17.59, 8.06, 5.24,
]  # round to 2 dp  # fmt: skip
WECS_ANNUAL_MEAN_GOLDEN = 16.68  # round to 2 dp
MIP_MONTHLY_GOLDEN = [
    7.59, 5.26, 3.86, 2.80, 5.26, 8.76, 37.91, 70.00, 58.32, 29.18, 14.00, 10.50,
]  # round to 2 dp  # fmt: skip
# Measured 2.8 m³/s in April, region 3 (guideline pages 148-149).
MIP_MEASUREMENT = {"measured_q_m3s": 2.8, "month": 4, "day": None, "abstractions_m3s": 0.0}


@pytest.fixture(autouse=True)
def _no_warnings() -> object:
    # Solu Khola is inside every calibration range: the golden run must be silent.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        yield


@pytest.mark.parametrize(("t", "golden"), sorted(FLOOD_GOLDEN.items()))
def test_wecs_flood_peak(solu_khola: Catchment, t: int, golden: int) -> None:
    floods = wecs_dhm.flood_peaks(solu_khola, return_periods=tuple(FLOOD_GOLDEN))
    assert round(floods[t].q_m3s) == golden


@pytest.mark.parametrize(("p", "golden"), sorted(FDC_GOLDEN.items()))
def test_wecs_flow_duration(solu_khola: Catchment, p: int, golden: float) -> None:
    fdc = wecs_dhm.flow_duration(solu_khola)
    assert round(fdc.points[p], 2) == golden
    assert round(fdc.at(p), 2) == golden


def test_wecs_flow_duration_has_exactly_the_guideline_points(solu_khola: Catchment) -> None:
    assert list(wecs_dhm.flow_duration(solu_khola).points) == list(FDC_GOLDEN)


@pytest.mark.parametrize(("month", "golden"), list(zip(MONTHS, WECS_MONTHLY_GOLDEN, strict=True)))
def test_wecs_monthly_flow(solu_khola: Catchment, month: str, golden: float) -> None:
    assert round(wecs_dhm.monthly_flows(solu_khola)[month], 2) == golden


def test_wecs_annual_mean(solu_khola: Catchment) -> None:
    assert round(wecs_dhm.monthly_flows(solu_khola).annual_mean, 2) == WECS_ANNUAL_MEAN_GOLDEN


@pytest.mark.parametrize(("month", "golden"), list(zip(MONTHS, MIP_MONTHLY_GOLDEN, strict=True)))
def test_mip_monthly_flow(solu_khola: Catchment, month: str, golden: float) -> None:
    hydro = mip.monthly_hydrograph(solu_khola, **MIP_MEASUREMENT)  # type: ignore[arg-type]
    assert round(hydro[month], 2) == golden


def test_spec_api_examples(solu_khola: Catchment) -> None:
    # The comments in the spec's "Public API" block.
    floods = wecs_dhm.flood_peaks(solu_khola, return_periods=(2, 5, 10, 20, 50, 100))
    assert int(floods[100].q_m3s) == 426
    assert round(wecs_dhm.flow_duration(solu_khola).at(95), 2) == 2.03
    monthly = wecs_dhm.monthly_flows(solu_khola)
    assert (round(monthly["Jul"], 2), round(monthly.annual_mean, 2)) == (43.86, 16.68)
    hydro = mip.monthly_hydrograph(
        solu_khola, measured_q_m3s=2.8, month=4, day=None, abstractions_m3s=0.0
    )
    assert round(hydro["Aug"], 2) == 70.00
    table = compare_monthly(monthly, hydro)
    assert [round(table[m].mip_m3s, 2) for m in MONTHS] == MIP_MONTHLY_GOLDEN
    assert [round(table[m].wecs_m3s, 2) for m in MONTHS] == WECS_MONTHLY_GOLDEN
