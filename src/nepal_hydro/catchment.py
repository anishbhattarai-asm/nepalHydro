"""The validated ``Catchment`` every method reads its inputs from.

Every field is optional. A method asks only for the fields it uses (see
:meth:`Catchment.require`), so ``flood_peaks`` works with only
``area_below_3000_km2`` set. Invalid geometry raises at construction; values
that are valid but outside a method's calibration range only warn, when that
method runs.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, fields
from typing import Literal

from nepal_hydro.warnings import OutOfCalibrationRangeWarning, emit

__all__ = ["AreaField", "Catchment", "MissingInputError"]

AreaField = Literal["area_km2", "area_below_5000_km2", "area_below_3000_km2"]
FloatField = Literal[AreaField, "monsoon_wetness_index_mm"]

MIP_REGIONS = range(1, 8)


class MissingInputError(ValueError):
    """A method needs a ``Catchment`` field that is not set."""

    def __init__(self, method: str, missing: Sequence[str]) -> None:
        self.method = method
        self.missing = tuple(missing)
        names = ", ".join(self.missing)
        super().__init__(f"{method} needs these Catchment fields, which are not set: {names}")


def _check_float(name: str, value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number or None, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


@dataclass(frozen=True)
class Catchment:
    """Catchment characteristics, in SI units named in each field.

    Rules (``ValueError`` when broken, checked for whichever fields are set):

    * ``area_km2 > 0``
    * ``0 <= area_below_5000_km2 <= area_km2``
    * ``0 <= area_below_3000_km2 <= area_below_5000_km2`` (and ``<= area_km2``)
    * ``monsoon_wetness_index_mm > 0``
    * ``mip_region`` in 1..7
    """

    name: str | None = None
    area_km2: float | None = None
    area_below_5000_km2: float | None = None
    area_below_3000_km2: float | None = None
    monsoon_wetness_index_mm: float | None = None
    mip_region: int | None = None

    def __post_init__(self) -> None:
        if self.name is not None and not isinstance(self.name, str):
            raise TypeError(f"name must be a string or None, got {self.name!r}")
        for f in fields(self):
            if f.name in ("name", "mip_region"):
                continue
            object.__setattr__(self, f.name, _check_float(f.name, getattr(self, f.name)))

        a, a5000, a3000 = self.area_km2, self.area_below_5000_km2, self.area_below_3000_km2
        if a is not None and a <= 0:
            raise ValueError(f"area_km2 must be > 0, got {a}")
        if a5000 is not None:
            if a5000 < 0:
                raise ValueError(f"area_below_5000_km2 must be >= 0, got {a5000}")
            if a is not None and a5000 > a:
                raise ValueError(f"area_below_5000_km2 ({a5000}) cannot exceed area_km2 ({a})")
        if a3000 is not None:
            if a3000 < 0:
                raise ValueError(f"area_below_3000_km2 must be >= 0, got {a3000}")
            if a5000 is not None and a3000 > a5000:
                raise ValueError(
                    f"area_below_3000_km2 ({a3000}) cannot exceed area_below_5000_km2 ({a5000})"
                )
            if a is not None and a3000 > a:
                raise ValueError(f"area_below_3000_km2 ({a3000}) cannot exceed area_km2 ({a})")

        mwi = self.monsoon_wetness_index_mm
        if mwi is not None and mwi <= 0:
            raise ValueError(f"monsoon_wetness_index_mm must be > 0, got {mwi}")

        region = self.mip_region
        if region is not None:
            if isinstance(region, bool) or not isinstance(region, int):
                raise TypeError(f"mip_region must be an integer or None, got {region!r}")
            if region not in MIP_REGIONS:
                raise ValueError(f"mip_region must be 1 to 7, got {region}")

    def require(self, method: str, *names: FloatField) -> tuple[float, ...]:
        """Values of the named fields, in order, or ``MissingInputError`` naming every gap."""
        values = [getattr(self, n) for n in names]
        missing = [n for n, v in zip(names, values, strict=True) if v is None]
        if missing:
            raise MissingInputError(method, missing)
        return tuple(values)

    def require_mip_region(self, method: str) -> int:
        """The MIP region, or ``MissingInputError`` if it is not set."""
        if self.mip_region is None:
            raise MissingInputError(method, ["mip_region"])
        return self.mip_region

    def check_calibration(
        self,
        method: str,
        names: Sequence[AreaField],
        area_range_km2: tuple[float, float],
        *,
        stacklevel: int = 1,
    ) -> list[str]:
        """Warn for each named area outside ``area_range_km2``; return the messages.

        The fields must already be set (call :meth:`require` first). ``stacklevel``
        counts from the caller, as in :func:`warnings.warn`.
        """
        low, high = area_range_km2
        messages = []
        for n in names:
            value = getattr(self, n)
            if value is not None and not low <= value <= high:
                messages.append(
                    emit(
                        f"{method}: {n} = {value:g} km² is outside the {low:g} to {high:g} km² "
                        "range the method was calibrated on; treat the result with caution",
                        OutOfCalibrationRangeWarning,
                        stacklevel=stacklevel + 1,
                    )
                )
        return messages
