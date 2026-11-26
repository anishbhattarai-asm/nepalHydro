"""Result types shared by every method, the CLI and ``compare``.

Results are frozen dataclasses holding full-precision floats: nothing here
rounds a stored value. Rounding happens only in ``__repr__`` and, when asked
for with ``decimals=``, in the JSON and CSV exports. Every result carries the
``method`` that produced it, the ``source`` citation and its ``warnings``.
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import math
import numbers
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import IO, Any, ClassVar, TypeVar

from nepal_hydro.coefficients import MONTHS

__all__ = [
    "ComparisonRow",
    "FloodEstimate",
    "FloodPeaks",
    "FlowDurationCurve",
    "MonthlyComparison",
    "MonthlyFlows",
    "result_from_dict",
]

_R = TypeVar("_R", bound="_Result")


def _rounded(value: Any, decimals: int | None) -> Any:
    if decimals is None:
        return value
    if isinstance(value, float):
        return round(value, decimals)
    if isinstance(value, dict):
        return {k: _rounded(v, decimals) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v, decimals) for v in value]
    return value


def _real(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{name} must be a number, got {value!r}")
    number = float(value)
    if math.isnan(number):
        raise ValueError(f"{name} must not be NaN")
    return number


def _flow(name: str, value: object) -> float:
    number = _real(name, value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a finite flow >= 0, got {value!r}")
    return number


@dataclass(frozen=True, kw_only=True)
class _Result:
    """Fields and exports common to every result."""

    method: str
    source: str
    warnings: tuple[str, ...] = ()

    _kind: ClassVar[str]
    _csv_header: ClassVar[tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings))
        for name in ("method", "source"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{type(self).__name__}.{name} must be a non-empty string")
        if not all(isinstance(w, str) for w in self.warnings):
            raise TypeError("warnings must be strings")

    # Subclasses supply their data rows and the extra dict fields.
    def _rows(self) -> list[tuple[Any, ...]]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _data(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    @classmethod
    def _from_data(  # pragma: no cover - abstract
        cls: type[_R], data: Mapping[str, Any], meta: dict[str, Any]
    ) -> _R:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """A plain, JSON-ready dict at full precision; :meth:`from_dict` rebuilds the result."""
        return {
            "type": self._kind,
            "method": self.method,
            "source": self.source,
            "warnings": list(self.warnings),
            **self._data(),
        }

    @classmethod
    def from_dict(cls: type[_R], data: Mapping[str, Any]) -> _R:
        if data.get("type") != cls._kind:
            raise ValueError(f"expected a {cls._kind} dict, got type {data.get('type')!r}")
        meta = {
            "method": data["method"],
            "source": data["source"],
            "warnings": tuple(data.get("warnings", ())),
        }
        return cls._from_data(data, meta)

    def to_json(self, *, indent: int | None = 2, decimals: int | None = None) -> str:
        """JSON text; full precision unless ``decimals`` is given."""
        return json.dumps(_rounded(self.to_dict(), decimals), indent=indent, ensure_ascii=False)

    def to_csv(
        self,
        path_or_buffer: str | os.PathLike[str] | IO[str] | None = None,
        *,
        decimals: int | None = None,
    ) -> str | None:
        """Write the data rows as CSV to a path or text buffer.

        With no target, return the CSV text instead. Full precision unless
        ``decimals`` is given.
        """
        rows = [tuple(_rounded(v, decimals) for v in row) for row in self._rows()]
        if path_or_buffer is None:
            buffer = io.StringIO()
            self._write_csv(buffer, rows)
            return buffer.getvalue()
        if isinstance(path_or_buffer, (str, os.PathLike)):
            with open(path_or_buffer, "w", newline="", encoding="utf-8") as fh:
                self._write_csv(fh, rows)
        else:
            self._write_csv(path_or_buffer, rows)
        return None

    def _write_csv(self, fh: IO[str], rows: Iterable[tuple[Any, ...]]) -> None:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(self._csv_header)
        writer.writerows(rows)

    def to_dataframe(self) -> Any:
        """A ``pandas.DataFrame`` of the data rows. Needs pandas, which is optional."""
        try:
            import pandas as pd  # type: ignore[import-not-found,import-untyped,unused-ignore]
        except ImportError:
            raise ImportError(
                "to_dataframe() needs pandas, which nepal-hydro does not install; "
                "run `pip install pandas`"
            ) from None
        frame = pd.DataFrame(self._rows(), columns=list(self._csv_header))
        frame.attrs.update(method=self.method, source=self.source, warnings=list(self.warnings))
        return frame

    def _repr_tail(self) -> str:
        n = len(self.warnings)
        return f"method={self.method!r}, {n} warning{'' if n == 1 else 's'}"


# ----------------------------------------------------------------------- floods


@dataclass(frozen=True)
class FloodEstimate:
    """One flood peak: ``q_m3s`` for return period ``return_period_yr``."""

    return_period_yr: float
    q_m3s: float

    def __post_init__(self) -> None:
        t = self.return_period_yr
        if isinstance(t, bool) or not isinstance(t, numbers.Real) or not t > 1:
            raise ValueError(f"return_period_yr must be a number > 1, got {t!r}")
        if isinstance(t, numbers.Integral):
            object.__setattr__(self, "return_period_yr", int(t))
        object.__setattr__(self, "q_m3s", _flow("q_m3s", self.q_m3s))

    def __repr__(self) -> str:
        return f"FloodEstimate(return_period_yr={self.return_period_yr}, q_m3s={self.q_m3s:.2f})"


@dataclass(frozen=True, kw_only=True, repr=False)
class FloodPeaks(_Result, Mapping[float, FloodEstimate]):
    """Flood peaks by return period: ``peaks[100].q_m3s``.

    ``sigma_ln`` is the standard deviation of ln Q in the log-normal fit.
    """

    estimates: Mapping[float, FloodEstimate]
    sigma_ln: float

    _kind: ClassVar[str] = "FloodPeaks"
    _csv_header: ClassVar[tuple[str, ...]] = ("return_period_yr", "q_m3s")

    def __post_init__(self) -> None:
        super().__post_init__()
        estimates = dict(self.estimates)
        for key, est in estimates.items():
            if not isinstance(est, FloodEstimate) or est.return_period_yr != key:
                raise ValueError(f"estimate for T={key!r} must be a FloodEstimate for that T")
        if not estimates:
            raise ValueError("FloodPeaks needs at least one estimate")
        object.__setattr__(self, "estimates", MappingProxyType(estimates))
        object.__setattr__(self, "sigma_ln", _real("sigma_ln", self.sigma_ln))

    def __getitem__(self, return_period_yr: float) -> FloodEstimate:
        return self.estimates[return_period_yr]

    def __iter__(self) -> Iterator[float]:
        return iter(self.estimates)

    def __len__(self) -> int:
        return len(self.estimates)

    def _rows(self) -> list[tuple[Any, ...]]:
        return [(e.return_period_yr, e.q_m3s) for e in self.estimates.values()]

    def _data(self) -> dict[str, Any]:
        return {
            "sigma_ln": self.sigma_ln,
            "estimates": [{"return_period_yr": t, "q_m3s": q} for t, q in self._rows()],
        }

    @classmethod
    def _from_data(cls, data: Mapping[str, Any], meta: dict[str, Any]) -> FloodPeaks:
        ests = [FloodEstimate(e["return_period_yr"], e["q_m3s"]) for e in data["estimates"]]
        return cls(
            estimates={e.return_period_yr: e for e in ests}, sigma_ln=data["sigma_ln"], **meta
        )

    def __repr__(self) -> str:
        peaks = ", ".join(f"Q{e.return_period_yr}={e.q_m3s:.2f}" for e in self.estimates.values())
        return f"FloodPeaks({peaks} m³/s, sigma_ln={self.sigma_ln:.4f}, {self._repr_tail()})"


# --------------------------------------------------------- flow duration curve


@dataclass(frozen=True, kw_only=True, repr=False)
class FlowDurationCurve(_Result):
    """Flows by percent of time exceeded: ``points[95]`` is Q95, in m³/s.

    :meth:`at` interpolates between table points in log-flow and never
    extrapolates beyond them.
    """

    points: Mapping[int, float]

    _kind: ClassVar[str] = "FlowDurationCurve"
    _csv_header: ClassVar[tuple[str, ...]] = ("exceedance_pct", "q_m3s")

    def __post_init__(self) -> None:
        super().__post_init__()
        points: dict[int, float] = {}
        for p, q in sorted(self.points.items()):
            if isinstance(p, bool) or not isinstance(p, numbers.Integral) or not 0 <= p <= 100:
                raise ValueError(f"exceedance must be an integer percent 0..100, got {p!r}")
            points[int(p)] = _flow(f"Q{p}", q)
        if not points:
            raise ValueError("FlowDurationCurve needs at least one point")
        object.__setattr__(self, "points", MappingProxyType(points))

    def at(self, exceedance_pct: float) -> float:
        """Flow exceeded ``exceedance_pct`` percent of the time, in m³/s.

        Between table points the flow is interpolated linearly in ln Q (where
        both neighbours are positive; linearly in Q if one is zero). Outside
        0..100, or outside the table's own range, it raises ``ValueError``.
        """
        p = _real("exceedance_pct", exceedance_pct)
        if not 0 <= p <= 100:
            raise ValueError(f"exceedance_pct must be within 0..100, got {exceedance_pct!r}")
        keys = list(self.points)
        if not keys[0] <= p <= keys[-1]:
            raise ValueError(
                f"exceedance_pct {exceedance_pct!r} is outside this curve's points "
                f"({keys[0]}..{keys[-1]}); the curve is never extrapolated"
            )
        for lo, hi in itertools.pairwise(keys):
            if lo <= p <= hi:
                break
        else:
            return self.points[keys[0]]  # a single-point curve, at that point
        q_lo, q_hi = self.points[lo], self.points[hi]
        if p == lo:
            return q_lo
        if p == hi:
            return q_hi
        frac = (p - lo) / (hi - lo)
        if q_lo > 0 and q_hi > 0:
            return math.exp(math.log(q_lo) + frac * (math.log(q_hi) - math.log(q_lo)))
        return q_lo + frac * (q_hi - q_lo)

    def _rows(self) -> list[tuple[Any, ...]]:
        return list(self.points.items())

    def _data(self) -> dict[str, Any]:
        return {"points": [{"exceedance_pct": p, "q_m3s": q} for p, q in self._rows()]}

    @classmethod
    def _from_data(cls, data: Mapping[str, Any], meta: dict[str, Any]) -> FlowDurationCurve:
        return cls(points={d["exceedance_pct"]: d["q_m3s"] for d in data["points"]}, **meta)

    def __repr__(self) -> str:
        pts = ", ".join(f"Q{p}={q:.2f}" for p, q in self.points.items())
        return f"FlowDurationCurve({pts} m³/s, {self._repr_tail()})"


# -------------------------------------------------------------- monthly flows


@dataclass(frozen=True, kw_only=True, repr=False)
class MonthlyFlows(_Result, Mapping[str, float]):
    """Mean flow for each month in m³/s, as a mapping ``"Jan"`` .. ``"Dec"``: ``flows["Jul"]``.

    Used by both WECS/DHM and MIP; ``method`` says which. Being a ``Mapping``,
    ``dict(flows)`` and ``pandas.Series(flows)`` work directly.
    """

    by_month: Mapping[str, float]

    _kind: ClassVar[str] = "MonthlyFlows"
    _csv_header: ClassVar[tuple[str, ...]] = ("month", "q_m3s")

    def __post_init__(self) -> None:
        super().__post_init__()
        if set(self.by_month) != set(MONTHS):
            raise ValueError(f"MonthlyFlows needs exactly the months {', '.join(MONTHS)}")
        object.__setattr__(
            self,
            "by_month",
            MappingProxyType({m: _flow(m, self.by_month[m]) for m in MONTHS}),
        )

    def __getitem__(self, month: str) -> float:
        return self.by_month[month]

    def __iter__(self) -> Iterator[str]:
        return iter(self.by_month)

    def __len__(self) -> int:
        return len(self.by_month)

    @property
    def annual_mean(self) -> float:
        """Arithmetic mean of the 12 monthly flows, in m³/s."""
        return math.fsum(self.by_month.values()) / len(MONTHS)

    def to_list(self) -> list[float]:
        """The 12 flows, January first."""
        return list(self.by_month.values())

    def _rows(self) -> list[tuple[Any, ...]]:
        return list(self.by_month.items())

    def _data(self) -> dict[str, Any]:
        return {"by_month": dict(self.by_month), "annual_mean": self.annual_mean}

    @classmethod
    def _from_data(cls, data: Mapping[str, Any], meta: dict[str, Any]) -> MonthlyFlows:
        return cls(by_month=data["by_month"], **meta)

    def __repr__(self) -> str:
        vals = ", ".join(f"{m}={q:.2f}" for m, q in self.by_month.items())
        return f"MonthlyFlows({vals}, mean={self.annual_mean:.2f} m³/s, {self._repr_tail()})"


# ----------------------------------------------------------------- comparison


@dataclass(frozen=True)
class ComparisonRow:
    """One row of a WECS vs MIP comparison.

    ``ratio_mip_over_wecs`` is ``mip_m3s / wecs_m3s``: above 1 means MIP gives
    more flow than WECS/DHM. It is None when the WECS flow is 0.
    """

    month: str
    wecs_m3s: float
    mip_m3s: float
    ratio_mip_over_wecs: float | None

    @classmethod
    def of(cls, month: str, wecs_m3s: float, mip_m3s: float) -> ComparisonRow:
        return cls(month, wecs_m3s, mip_m3s, mip_m3s / wecs_m3s if wecs_m3s > 0 else None)

    def __repr__(self) -> str:
        r = self.ratio_mip_over_wecs
        ratio = "n/a" if r is None else f"{r:.2f}"
        return (
            f"ComparisonRow({self.month}: wecs={self.wecs_m3s:.2f}, "
            f"mip={self.mip_m3s:.2f} m³/s, mip/wecs={ratio})"
        )


@dataclass(frozen=True, kw_only=True, repr=False)
class MonthlyComparison(_Result, Mapping[str, ComparisonRow]):
    """WECS/DHM and MIP monthly flows side by side: ``comparison["Jul"].ratio``.

    A mapping from month name to :class:`ComparisonRow`; :attr:`annual` compares
    the annual means. The ratio is MIP over WECS (``ratio_mip_over_wecs``, also
    the CSV and dict column name). Built by :func:`nepal_hydro.compare_monthly`.
    """

    wecs: MonthlyFlows
    mip: MonthlyFlows

    _kind: ClassVar[str] = "MonthlyComparison"
    _csv_header: ClassVar[tuple[str, ...]] = (
        "month", "wecs_m3s", "mip_m3s", "ratio_mip_over_wecs",
    )  # fmt: skip

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("wecs", "mip"):
            if not isinstance(getattr(self, name), MonthlyFlows):
                raise TypeError(f"{name} must be a MonthlyFlows result")

    def __getitem__(self, month: str) -> ComparisonRow:
        return ComparisonRow.of(month, self.wecs[month], self.mip[month])

    def __iter__(self) -> Iterator[str]:
        return iter(MONTHS)

    def __len__(self) -> int:
        return len(MONTHS)

    @property
    def annual(self) -> ComparisonRow:
        """The annual means compared, as a row labelled ``"annual"``."""
        return ComparisonRow.of("annual", self.wecs.annual_mean, self.mip.annual_mean)

    def _rows(self) -> list[tuple[Any, ...]]:
        rows = [*self.values(), self.annual]
        return [(r.month, r.wecs_m3s, r.mip_m3s, r.ratio_mip_over_wecs) for r in rows]

    def _data(self) -> dict[str, Any]:
        return {
            "rows": [dict(zip(self._csv_header, row, strict=True)) for row in self._rows()],
            "wecs": self.wecs.to_dict(),
            "mip": self.mip.to_dict(),
        }

    @classmethod
    def _from_data(cls, data: Mapping[str, Any], meta: dict[str, Any]) -> MonthlyComparison:
        return cls(
            wecs=MonthlyFlows.from_dict(data["wecs"]),
            mip=MonthlyFlows.from_dict(data["mip"]),
            **meta,
        )

    def __repr__(self) -> str:
        a = self.annual
        r = a.ratio_mip_over_wecs
        ratio = "n/a" if r is None else f"{r:.2f}"
        return (
            f"MonthlyComparison(annual mean wecs={a.wecs_m3s:.2f}, mip={a.mip_m3s:.2f} m³/s, "
            f"mip/wecs={ratio}, {self._repr_tail()})"
        )


AnyResult = FloodPeaks | FlowDurationCurve | MonthlyFlows | MonthlyComparison

_TYPES: dict[str, type[_Result]] = {
    cls._kind: cls for cls in (FloodPeaks, FlowDurationCurve, MonthlyFlows, MonthlyComparison)
}


def result_from_dict(data: Mapping[str, Any]) -> AnyResult:
    """Rebuild any result from its :meth:`to_dict` output, using its ``type`` field."""
    kind = data.get("type")
    if kind not in _TYPES:
        raise ValueError(f"unknown result type {kind!r}")
    result = _TYPES[kind].from_dict(data)
    assert isinstance(result, (FloodPeaks, FlowDurationCurve, MonthlyFlows, MonthlyComparison))
    return result
