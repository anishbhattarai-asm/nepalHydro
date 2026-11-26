"""Every rule in the spec's Catchment table raises or warns exactly as listed."""

from __future__ import annotations

import math
import warnings
from typing import Any

import pytest

from nepal_hydro import (
    Catchment,
    HydroWarning,
    MissingInputError,
    OutOfCalibrationRangeWarning,
    UnverifiedCoefficientWarning,
)
from nepal_hydro.coefficients import load_wecs_dhm

SOLU_KHOLA: dict[str, Any] = {
    "name": "Solu Khola",
    "area_km2": 330,
    "area_below_5000_km2": 308.5,
    "area_below_3000_km2": 97.7,
    "monsoon_wetness_index_mm": 1500,
    "mip_region": 3,
}
CAL = load_wecs_dhm().calibration_area_km2


def test_solu_khola_is_valid_and_stores_floats() -> None:
    c = Catchment(**SOLU_KHOLA)
    assert c.area_km2 == 330.0
    assert isinstance(c.area_km2, float)
    assert isinstance(c.monsoon_wetness_index_mm, float)
    assert c.mip_region == 3


def test_every_field_is_optional() -> None:
    c = Catchment()
    assert all(
        getattr(c, f) is None
        for f in ("name", "area_km2", "area_below_5000_km2", "area_below_3000_km2",
                  "monsoon_wetness_index_mm", "mip_region")
    )  # fmt: skip


def test_catchment_is_frozen() -> None:
    c = Catchment(area_km2=10)
    with pytest.raises(AttributeError):
        c.area_km2 = 20  # type: ignore[misc]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"area_km2": 0}, "area_km2 must be > 0"),
        ({"area_km2": -5}, "area_km2 must be > 0"),
        ({"area_below_5000_km2": -1}, "area_below_5000_km2 must be >= 0"),
        ({"area_km2": 100, "area_below_5000_km2": 100.1}, "cannot exceed area_km2"),
        ({"area_below_3000_km2": -0.1}, "area_below_3000_km2 must be >= 0"),
        ({"area_below_5000_km2": 50, "area_below_3000_km2": 51}, "cannot exceed area_below_5000"),
        ({"area_km2": 50, "area_below_3000_km2": 51}, "cannot exceed area_km2"),
        ({"monsoon_wetness_index_mm": 0}, "monsoon_wetness_index_mm must be > 0"),
        ({"monsoon_wetness_index_mm": -100}, "monsoon_wetness_index_mm must be > 0"),
        ({"mip_region": 0}, "mip_region must be 1 to 7"),
        ({"mip_region": 8}, "mip_region must be 1 to 7"),
        ({"area_km2": math.nan}, "must be finite"),
        ({"area_below_3000_km2": math.inf}, "must be finite"),
    ],
)
def test_invalid_geometry_raises_value_error(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Catchment(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": 5},
        {"area_km2": "330"},
        {"monsoon_wetness_index_mm": "1500"},
        {"mip_region": "3"},
        {"area_below_5000_km2": True},
        {"mip_region": 3.0},
        {"mip_region": True},
    ],
)
def test_wrong_types_raise_type_error(kwargs: dict[str, Any]) -> None:
    with pytest.raises(TypeError):
        Catchment(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"area_km2": 100, "area_below_5000_km2": 100, "area_below_3000_km2": 100},
        {"area_km2": 100, "area_below_5000_km2": 0, "area_below_3000_km2": 0},
        {"mip_region": 1},
        {"mip_region": 7},
    ],
)
def test_boundaries_are_allowed(kwargs: dict[str, Any]) -> None:
    Catchment(**kwargs)


def test_partial_catchments_check_only_the_pairs_present() -> None:
    # A3000 alone, or A3000 with only A, is enough for flood peaks.
    assert Catchment(area_below_3000_km2=97.7).area_below_3000_km2 == 97.7
    assert Catchment(area_km2=330, area_below_3000_km2=97.7).area_km2 == 330


# ----------------------------------------------------------------- require()


def test_require_returns_values_in_order() -> None:
    c = Catchment(**SOLU_KHOLA)
    assert c.require("m", "monsoon_wetness_index_mm", "area_km2") == (1500.0, 330.0)
    assert c.require_mip_region("m") == 3


def test_require_needs_only_the_named_fields() -> None:
    c = Catchment(area_below_3000_km2=97.7)
    assert c.require("WECS/DHM flood peaks", "area_below_3000_km2") == (97.7,)


def test_missing_field_names_every_gap() -> None:
    c = Catchment(area_km2=330)
    with pytest.raises(MissingInputError) as info:
        c.require("WECS/DHM flow duration", "area_km2", "area_below_5000_km2",
                  "monsoon_wetness_index_mm")  # fmt: skip
    err = info.value
    assert err.method == "WECS/DHM flow duration"
    assert err.missing == ("area_below_5000_km2", "monsoon_wetness_index_mm")
    assert "WECS/DHM flow duration" in str(err)
    assert "area_below_5000_km2, monsoon_wetness_index_mm" in str(err)
    assert "area_km2," not in str(err)


def test_missing_mip_region() -> None:
    with pytest.raises(MissingInputError, match="mip_region") as info:
        Catchment(area_km2=10).require_mip_region("MIP monthly hydrograph")
    assert info.value.missing == ("mip_region",)


def test_missing_input_error_is_a_value_error() -> None:
    assert issubclass(MissingInputError, ValueError)


# ------------------------------------------------------ calibration warnings
#
# The 4 to 54 100 km² range is for total basin area A. A is checked at both
# ends whenever it is set; without A, the sub-areas a method uses are checked
# against the upper end only.

SUBS: list[Any] = ["area_below_5000_km2", "area_below_3000_km2"]


def _silent(c: Catchment, subs: list[Any]) -> list[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return c.check_calibration("WECS/DHM", subs, CAL)


@pytest.mark.parametrize("area", [3.99, 0.5, 54100.5, 60000])
def test_total_area_outside_range_warns(area: float) -> None:
    c = Catchment(area_km2=area)
    with pytest.warns(OutOfCalibrationRangeWarning, match="area_km2") as record:
        messages = c.check_calibration("WECS/DHM", [], CAL)
    assert len(record) == 1
    assert messages == [str(record[0].message)]
    assert "4 to 54100 km²" in messages[0]


@pytest.mark.parametrize("area", [4, 330, 54100])
def test_total_area_inside_range_is_silent(area: float) -> None:
    assert _silent(Catchment(area_km2=area), SUBS) == []


def test_total_area_is_checked_even_if_the_method_does_not_use_it() -> None:
    # Flood peaks use only A3000, but a set A still says the basin is uncalibrated.
    c = Catchment(area_km2=2, area_below_3000_km2=1)
    with pytest.warns(OutOfCalibrationRangeWarning, match="area_km2 = 2 "):
        assert len(c.check_calibration("WECS/DHM", ["area_below_3000_km2"], CAL)) == 1


@pytest.mark.parametrize("value", [0, 0.5, 3.99])
def test_small_or_zero_sub_areas_never_warn(value: float) -> None:
    # A3000 = 0 is valid (the formulas use A3000 + 1); small sub-areas are normal.
    assert _silent(Catchment(area_below_5000_km2=value, area_below_3000_km2=value), SUBS) == []
    assert _silent(Catchment(area_km2=330, area_below_3000_km2=value), SUBS) == []


def test_large_sub_area_warns_when_total_area_is_not_set() -> None:
    c = Catchment(area_below_5000_km2=60000, area_below_3000_km2=55000)
    with pytest.warns(OutOfCalibrationRangeWarning) as record:
        messages = c.check_calibration("WECS/DHM", SUBS, CAL)
    assert len(record) == len(messages) == 2
    assert "area_below_5000_km2 = 60000" in messages[0]
    assert "area_below_3000_km2 = 55000" in messages[1]


def test_large_sub_area_with_total_area_warns_once_for_a() -> None:
    c = Catchment(area_km2=70000, area_below_5000_km2=60000, area_below_3000_km2=55000)
    with pytest.warns(OutOfCalibrationRangeWarning) as record:
        messages = c.check_calibration("WECS/DHM", SUBS, CAL)
    assert len(record) == 1
    assert "area_km2 = 70000" in messages[0]


def test_only_the_named_sub_areas_are_checked() -> None:
    c = Catchment(area_below_5000_km2=60000, area_below_3000_km2=50)
    assert _silent(c, ["area_below_3000_km2"]) == []


def test_sub_area_at_upper_bound_is_silent() -> None:
    assert _silent(Catchment(area_below_5000_km2=54100), SUBS) == []


def test_calibration_warning_points_at_the_caller() -> None:
    c = Catchment(area_km2=1)
    with pytest.warns(OutOfCalibrationRangeWarning) as record:
        c.check_calibration("WECS/DHM", [], CAL)
    assert record[0].filename == __file__


def test_valid_but_uncalibrated_input_does_not_raise() -> None:
    # The table's rule: out of calibration range warns, it never stops the calculation.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Catchment(area_km2=1, area_below_5000_km2=1, area_below_3000_km2=0)


# ------------------------------------------------------------ numeric types


def test_numpy_scalars_are_accepted_and_stored_as_builtins() -> None:
    np = pytest.importorskip("numpy")
    c = Catchment(
        area_km2=np.float64(330),
        area_below_5000_km2=np.int64(308),
        area_below_3000_km2=np.float32(97.7),
        monsoon_wetness_index_mm=np.int64(1500),
        mip_region=np.int64(3),
    )
    assert type(c.area_km2) is float
    assert type(c.area_below_5000_km2) is float
    assert type(c.monsoon_wetness_index_mm) is float
    assert type(c.mip_region) is int
    assert (c.area_km2, c.area_below_5000_km2, c.mip_region) == (330.0, 308.0, 3)


def test_numpy_scalars_are_still_validated() -> None:
    np = pytest.importorskip("numpy")
    with pytest.raises(ValueError, match="mip_region must be 1 to 7"):
        Catchment(mip_region=np.int64(9))
    with pytest.raises(ValueError, match="must be finite"):
        Catchment(area_km2=np.float64("nan"))
    with pytest.raises(TypeError):
        Catchment(mip_region=np.float64(3))
    with pytest.raises(TypeError):
        Catchment(area_km2=np.bool_(True))


def test_other_real_and_integral_types_are_accepted() -> None:
    from fractions import Fraction

    # Accepted at runtime (numbers.Real); the static annotation stays float.
    c = Catchment(area_km2=Fraction(661, 2), mip_region=3)  # type: ignore[arg-type]
    assert c.area_km2 == 330.5


def test_warning_hierarchy() -> None:
    assert issubclass(HydroWarning, UserWarning)
    assert issubclass(OutOfCalibrationRangeWarning, HydroWarning)
    assert issubclass(UnverifiedCoefficientWarning, HydroWarning)
