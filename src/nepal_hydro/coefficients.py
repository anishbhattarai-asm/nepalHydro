"""Load the method coefficients from ``data/*.json`` into frozen dataclasses.

Every coefficient the library uses lives in a JSON data file next to its source
citation. This module reads those files once (``functools.cache``), validates
their shape at load time and exposes them as immutable objects. No coefficient
appears as a literal in Python code.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from types import MappingProxyType
from typing import Any, Literal

__all__ = [
    "MONTHS",
    "SCHEMA_VERSION",
    "CoefficientDataError",
    "FdcLogLinear",
    "FdcSquaredSqrt",
    "FloodPowerLaw",
    "MipCoefficients",
    "MipRegion",
    "MonthlyCoefficient",
    "WecsDhmCoefficients",
    "load_mip",
    "load_wecs_dhm",
    "parse_mip",
    "parse_wecs_dhm",
]

SCHEMA_VERSION = 1
MONTHS: tuple[str, ...] = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)  # fmt: skip

Variable = Literal["A", "A5000+1", "A3000+1"]
_VARIABLES: frozenset[str] = frozenset({"A", "A5000+1", "A3000+1"})

WECS_DHM_FILE = "wecs_dhm_1990.json"
MIP_FILE = "mip_1982.json"


class CoefficientDataError(ValueError):
    """A coefficient data file is missing, malformed or fails validation."""


# --------------------------------------------------------------------------- types


@dataclass(frozen=True)
class FloodPowerLaw:
    """``Q_T = alpha * x ** beta`` for one anchor return period."""

    return_period_yr: int
    alpha: float
    beta: float
    x: Variable


@dataclass(frozen=True)
class FdcLogLinear:
    """``ln Q_P = c + a * ln(x) + b * ln(MWI)``."""

    exceedance_pct: int
    c: float
    a: float
    x: Variable
    b: float


@dataclass(frozen=True)
class FdcSquaredSqrt:
    """``Q_P = (c + a * sqrt(x)) ** 2`` (used for Q100)."""

    exceedance_pct: int
    c: float
    a: float
    x: Variable


FdcCoefficient = FdcLogLinear | FdcSquaredSqrt


@dataclass(frozen=True)
class MonthlyCoefficient:
    """``Q_month = c * A**a1 * (A5000 + 1)**a2 * MWI**a3``."""

    month: str
    c: float
    a1: float
    a2: float
    a3: float


@dataclass(frozen=True)
class WecsDhmCoefficients:
    schema_version: int
    method: str
    source: str
    calibration_area_km2: tuple[float, float]
    calibration_source: str
    flood: Mapping[int, FloodPowerLaw]
    flood_source: str
    fdc: Mapping[int, FdcCoefficient]
    fdc_source: str
    monthly: Mapping[str, MonthlyCoefficient]
    monthly_source: str
    verified: Mapping[str, str]


@dataclass(frozen=True)
class MipRegion:
    region: int
    ordinates: Mapping[str, float]
    verified: bool
    note: str


@dataclass(frozen=True)
class MipCoefficients:
    schema_version: int
    method: str
    source: str
    regions: Mapping[int, MipRegion]


# ------------------------------------------------------------------ field helpers


def _fail(where: str, problem: str) -> CoefficientDataError:
    return CoefficientDataError(f"{where}: {problem}")


def _obj(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(where, f"expected an object, got {type(value).__name__}")
    return value


def _get(obj: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in obj:
        raise _fail(where, f"missing key {key!r}")
    return obj[key]


def _num(obj: Mapping[str, Any], key: str, where: str) -> float:
    value = _get(obj, key, where)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(f"{where}.{key}", f"expected a number, got {value!r}")
    if not math.isfinite(value):
        raise _fail(f"{where}.{key}", f"expected a finite number, got {value!r}")
    return float(value)


def _text(obj: Mapping[str, Any], key: str, where: str, *, allow_empty: bool = False) -> str:
    value = _get(obj, key, where)
    if not isinstance(value, str):
        raise _fail(f"{where}.{key}", f"expected a string, got {value!r}")
    if not allow_empty and not value.strip():
        raise _fail(f"{where}.{key}", "must not be empty")
    return value


def _variable(obj: Mapping[str, Any], key: str, where: str) -> Variable:
    value = _text(obj, key, where)
    if value not in _VARIABLES:
        raise _fail(
            f"{where}.{key}", f"unknown variable {value!r}; expected one of {sorted(_VARIABLES)}"
        )
    return value  # type: ignore[return-value]


def _int_key(key: str, where: str) -> int:
    try:
        number = int(key)
    except ValueError:
        raise _fail(where, f"key {key!r} is not an integer") from None
    if str(number) != key:
        raise _fail(where, f"key {key!r} is not a canonical integer")
    return number


def _check_schema(data: Mapping[str, Any], where: str) -> int:
    version = _get(data, "schema_version", where)
    if version != SCHEMA_VERSION:
        raise _fail(
            f"{where}.schema_version",
            f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}",
        )
    return SCHEMA_VERSION


def _check_months(keys: Mapping[str, Any], where: str) -> None:
    if tuple(keys) != MONTHS:
        raise _fail(where, f"expected the 12 months Jan..Dec in order, got {list(keys)}")


# ------------------------------------------------------------------------ parsers


def parse_wecs_dhm(raw: Any, where: str = WECS_DHM_FILE) -> WecsDhmCoefficients:
    """Validate a decoded WECS/DHM JSON document and build its dataclasses."""
    data = _obj(raw, where)
    version = _check_schema(data, where)

    cal = _obj(_get(data, "calibration", where), f"{where}.calibration")
    cal_area = _obj(_get(cal, "area_km2", f"{where}.calibration"), f"{where}.calibration.area_km2")
    area_min = _num(cal_area, "min", f"{where}.calibration.area_km2")
    area_max = _num(cal_area, "max", f"{where}.calibration.area_km2")
    if not 0 < area_min < area_max:
        raise _fail(f"{where}.calibration.area_km2", "need 0 < min < max")

    flood_sec = _obj(_get(data, "flood", where), f"{where}.flood")
    flood: dict[int, FloodPowerLaw] = {}
    for key, value in _obj(
        _get(flood_sec, "coefficients", f"{where}.flood"), f"{where}.flood.coefficients"
    ).items():
        w = f"{where}.flood.coefficients.{key}"
        entry = _obj(value, w)
        t = _int_key(key, f"{where}.flood.coefficients")
        flood[t] = FloodPowerLaw(
            t, _num(entry, "alpha", w), _num(entry, "beta", w), _variable(entry, "x", w)
        )
    if set(flood) != {2, 100}:
        raise _fail(
            f"{where}.flood.coefficients",
            f"expected anchor return periods 2 and 100, got {sorted(flood)}",
        )

    fdc_sec = _obj(_get(data, "fdc", where), f"{where}.fdc")
    fdc: dict[int, FdcCoefficient] = {}
    for key, value in _obj(
        _get(fdc_sec, "coefficients", f"{where}.fdc"), f"{where}.fdc.coefficients"
    ).items():
        w = f"{where}.fdc.coefficients.{key}"
        entry = _obj(value, w)
        p = _int_key(key, f"{where}.fdc.coefficients")
        if not 0 <= p <= 100:
            raise _fail(w, "exceedance must be within 0..100")
        form = _text(entry, "form", w)
        if form == "log_linear":
            fdc[p] = FdcLogLinear(
                p,
                _num(entry, "c", w),
                _num(entry, "a", w),
                _variable(entry, "x", w),
                _num(entry, "b", w),
            )
        elif form == "squared_sqrt":
            fdc[p] = FdcSquaredSqrt(
                p, _num(entry, "c", w), _num(entry, "a", w), _variable(entry, "x", w)
            )
        else:
            raise _fail(f"{w}.form", f"unknown form {form!r}")
    if list(fdc) != sorted(fdc):
        raise _fail(f"{where}.fdc.coefficients", "exceedance levels must be in ascending order")
    if 0 not in fdc or 100 not in fdc:
        raise _fail(f"{where}.fdc.coefficients", "must include exceedance levels 0 and 100")

    monthly_sec = _obj(_get(data, "monthly", where), f"{where}.monthly")
    monthly_raw = _obj(
        _get(monthly_sec, "coefficients", f"{where}.monthly"), f"{where}.monthly.coefficients"
    )
    _check_months(monthly_raw, f"{where}.monthly.coefficients")
    monthly: dict[str, MonthlyCoefficient] = {}
    for month, value in monthly_raw.items():
        w = f"{where}.monthly.coefficients.{month}"
        entry = _obj(value, w)
        monthly[month] = MonthlyCoefficient(
            month,
            _num(entry, "c", w),
            _num(entry, "a1", w),
            _num(entry, "a2", w),
            _num(entry, "a3", w),
        )
        if monthly[month].c <= 0:
            raise _fail(f"{w}.c", "must be positive")

    verified_raw = _obj(_get(data, "verified", where), f"{where}.verified")
    verified = {k: _text(verified_raw, k, f"{where}.verified") for k in verified_raw}

    return WecsDhmCoefficients(
        schema_version=version,
        method=_text(data, "method", where),
        source=_text(data, "source", where),
        calibration_area_km2=(area_min, area_max),
        calibration_source=_text(cal, "source", f"{where}.calibration"),
        flood=MappingProxyType(flood),
        flood_source=_text(flood_sec, "source", f"{where}.flood"),
        fdc=MappingProxyType(fdc),
        fdc_source=_text(fdc_sec, "source", f"{where}.fdc"),
        monthly=MappingProxyType(monthly),
        monthly_source=_text(monthly_sec, "source", f"{where}.monthly"),
        verified=MappingProxyType(verified),
    )


def parse_mip(raw: Any, where: str = MIP_FILE) -> MipCoefficients:
    """Validate a decoded MIP JSON document and build its dataclasses."""
    data = _obj(raw, where)
    version = _check_schema(data, where)
    regions_raw = _obj(_get(data, "regions", where), f"{where}.regions")
    regions: dict[int, MipRegion] = {}
    for key, value in regions_raw.items():
        w = f"{where}.regions.{key}"
        entry = _obj(value, w)
        region = _int_key(key, f"{where}.regions")
        verified = _get(entry, "verified", w)
        if not isinstance(verified, bool):
            raise _fail(f"{w}.verified", f"expected true or false, got {verified!r}")
        ords_raw = _obj(_get(entry, "ordinates", w), f"{w}.ordinates")
        _check_months(ords_raw, f"{w}.ordinates")
        ordinates = {m: _num(ords_raw, m, f"{w}.ordinates") for m in MONTHS}
        if any(v <= 0 for v in ordinates.values()):
            raise _fail(f"{w}.ordinates", "every ordinate must be positive")
        if ordinates["Apr"] != 1.0:
            raise _fail(f"{w}.ordinates.Apr", "ordinates are normalised to April = 1.00")
        note = _text(entry, "note", w, allow_empty=verified)
        regions[region] = MipRegion(region, MappingProxyType(ordinates), verified, note)
    if sorted(regions) != list(range(1, 8)):
        raise _fail(f"{where}.regions", f"expected regions 1..7, got {sorted(regions)}")
    return MipCoefficients(
        schema_version=version,
        method=_text(data, "method", where),
        source=_text(data, "source", where),
        regions=MappingProxyType(dict(sorted(regions.items()))),
    )


# ------------------------------------------------------------------------ loaders


def _read_json(name: str) -> Any:
    try:
        text = (
            resources.files("nepal_hydro")
            .joinpath("data")
            .joinpath(name)
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        raise CoefficientDataError(f"{name}: data file not found in the package") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CoefficientDataError(f"{name}: invalid JSON ({exc})") from exc


@cache
def load_wecs_dhm() -> WecsDhmCoefficients:
    """The WECS/DHM (1990) coefficients, loaded and validated once."""
    return parse_wecs_dhm(_read_json(WECS_DHM_FILE))


@cache
def load_mip() -> MipCoefficients:
    """The MIP (1982) regional ordinates, loaded and validated once."""
    return parse_mip(_read_json(MIP_FILE))
