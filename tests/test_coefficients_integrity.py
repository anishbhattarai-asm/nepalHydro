"""Coefficient data integrity: shape, provenance, and agreement with the spec tables."""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from nepal_hydro import coefficients as co
from nepal_hydro.coefficients import (
    MONTHS,
    CoefficientDataError,
    FdcLogLinear,
    FdcSquaredSqrt,
    load_mip,
    load_wecs_dhm,
    parse_mip,
    parse_wecs_dhm,
)

SPEC = Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE.md"


def _raw(name: str) -> dict[str, Any]:
    text = resources.files("nepal_hydro").joinpath("data", name).read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def _num(cell: str) -> float:
    return float(cell.replace("\u2212", "-").strip())


def _spec_table(first_header: str) -> list[list[str]]:
    """Rows (without the header and divider) of the spec table whose first header cell matches."""
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == first_header:
            rows = []
            for row in lines[i + 2 :]:
                if not row.startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return rows
    raise AssertionError(f"table starting with {first_header!r} not found in {SPEC}")


# ------------------------------------------------------------------ loaded data


def test_loaders_are_cached() -> None:
    assert load_wecs_dhm() is load_wecs_dhm()
    assert load_mip() is load_mip()


def test_schema_versions() -> None:
    assert load_wecs_dhm().schema_version == co.SCHEMA_VERSION
    assert load_mip().schema_version == co.SCHEMA_VERSION
    assert _raw(co.WECS_DHM_FILE)["schema_version"] == co.SCHEMA_VERSION
    assert _raw(co.MIP_FILE)["schema_version"] == co.SCHEMA_VERSION


def test_twelve_months_in_every_table() -> None:
    assert tuple(load_wecs_dhm().monthly) == MONTHS
    for region in load_mip().regions.values():
        assert tuple(region.ordinates) == MONTHS


def test_april_is_one_in_every_mip_region() -> None:
    regions = load_mip().regions
    assert sorted(regions) == list(range(1, 8))
    for region in regions.values():
        assert region.ordinates["Apr"] == 1.0


def test_every_entry_has_a_source() -> None:
    w = load_wecs_dhm()
    for src in (w.source, w.calibration_source, w.flood_source, w.fdc_source, w.monthly_source):
        assert "Civil Works Guidelines for Micro-Hydropower in Nepal" in src
    m = load_mip()
    assert "Table A4" in m.source
    raw = _raw(co.WECS_DHM_FILE)
    for section in ("calibration", "flood", "fdc", "monthly"):
        assert raw[section]["source"].strip()


def test_flagged_items_are_marked() -> None:
    w = load_wecs_dhm()
    assert set(w.verified) == {"fdc.80", "fdc.100"}
    regions = load_mip().regions
    assert regions[4].verified is False
    assert "6.89" in regions[4].note
    assert all(r.verified for n, r in regions.items() if n != 4)


def test_data_is_immutable() -> None:
    w = load_wecs_dhm()
    with pytest.raises(TypeError):
        w.monthly["Jan"] = w.monthly["Feb"]  # type: ignore[index]
    with pytest.raises(AttributeError):
        w.method = "x"  # type: ignore[misc]


def test_calibration_range() -> None:
    assert load_wecs_dhm().calibration_area_km2 == (4.0, 54100.0)


# ------------------------------------------------------- agreement with the spec


def test_fdc_matches_spec() -> None:
    fdc = load_wecs_dhm().fdc
    rows = _spec_table("P (%)")
    assert [int(r[0]) for r in rows] == [p for p in fdc if p != 100]
    for p_cell, c, a, x, b in rows:
        entry = fdc[int(p_cell)]
        assert isinstance(entry, FdcLogLinear)
        assert (entry.c, entry.a, entry.b) == (_num(c), _num(a), _num(b))
        assert entry.x == x.replace(" ", "")


def test_fdc_q100_matches_spec() -> None:
    q100 = load_wecs_dhm().fdc[100]
    assert isinstance(q100, FdcSquaredSqrt)
    m = re.search(
        r"Q_\{100\\%\} = \\big\((\S+) \+ (\S+)\\,\\sqrt\{A_\{5000\} \+ 1\}",
        SPEC.read_text(encoding="utf-8"),
    )
    assert m is not None
    assert (q100.c, q100.a, q100.x) == (_num(m[1]), _num(m[2]), "A5000+1")


def test_flood_matches_spec() -> None:
    flood = load_wecs_dhm().flood
    text = SPEC.read_text(encoding="utf-8")
    for t in (2, 100):
        m = re.search(rf"Q_{{?{t}}}? = (\S+)\\,\(A_\{{3000\}} \+ 1\)\^\{{(\S+)\}}", text)
        assert m is not None, t
        assert (flood[t].alpha, flood[t].beta, flood[t].x) == (_num(m[1]), _num(m[2]), "A3000+1")


def test_monthly_matches_spec() -> None:
    monthly = load_wecs_dhm().monthly
    rows = _spec_table("Month")
    assert [r[0] for r in rows] == list(MONTHS)
    for month, c, a1, a2, a3 in rows:
        e = monthly[month]
        assert (e.c, e.a1, e.a2, e.a3) == (_num(c), _num(a1), _num(a2), _num(a3))


def test_mip_matches_spec() -> None:
    regions = load_mip().regions
    rows = _spec_table("Region")
    assert len(rows) == 7
    for row in rows:
        region = int(row[0].split()[0])
        assert [regions[region].ordinates[m] for m in MONTHS] == [_num(v) for v in row[1:]]
        assert regions[region].verified is ("unconfirmed" not in row[0])


# ------------------------------------------------------------- load-time checks

Mutator = Callable[[dict[str, Any]], None]


def _set(path: str, value: Any) -> Mutator:
    *parents, last = path.split(".")

    def mutate(doc: dict[str, Any]) -> None:
        node = doc
        for part in parents:
            node = node[part]
        node[last] = value

    return mutate


def _delete(path: str) -> Mutator:
    *parents, last = path.split(".")

    def mutate(doc: dict[str, Any]) -> None:
        node = doc
        for part in parents:
            node = node[part]
        del node[last]

    return mutate


def _reverse_months(path: str) -> Mutator:
    def mutate(doc: dict[str, Any]) -> None:
        node = doc
        for part in path.split("."):
            node = node[part]
        items = list(node.items())
        node.clear()
        node.update(reversed(items))

    return mutate


WECS_BREAKAGES: dict[str, tuple[Mutator, str]] = {
    "schema_version": (_set("schema_version", 2), "unsupported schema_version"),
    "missing method": (_delete("method"), "missing key 'method'"),
    "empty source": (_set("source", "  "), "must not be empty"),
    "source not str": (_set("source", 3), "expected a string"),
    "calibration order": (_set("calibration.area_km2.min", 60000), "0 < min < max"),
    "flood anchor": (_delete("flood.coefficients.100"), "anchor return periods"),
    "flood bool": (_set("flood.coefficients.2.alpha", True), "expected a number"),
    "flood string": (_set("flood.coefficients.2.beta", "0.87"), "expected a number"),
    "flood nan": (_set("flood.coefficients.2.beta", math.nan), "finite"),
    "flood key": (_set("flood.coefficients.two", {}), "not an integer"),
    "flood key form": (_set("flood.coefficients.02", {}), "canonical integer"),
    "variable": (_set("fdc.coefficients.0.x", "A4000+1"), "unknown variable"),
    "fdc form": (_set("fdc.coefficients.5.form", "cubic"), "unknown form"),
    "fdc range": (_set("fdc.coefficients.101", {"form": "log_linear"}), "within 0..100"),
    "fdc order": (
        _set("fdc.coefficients.1", {"form": "squared_sqrt", "c": 0, "a": 1, "x": "A"}),
        "ascending",
    ),
    "fdc ends": (_delete("fdc.coefficients.100"), "0 and 100"),
    "fdc entry type": (_set("fdc.coefficients.5", [1, 2]), "expected an object"),
    "month missing": (_delete("monthly.coefficients.Jul"), "12 months"),
    "month order": (_reverse_months("monthly.coefficients"), "12 months"),
    "month c": (_set("monthly.coefficients.Jan.c", 0), "must be positive"),
    "verified text": (_set("verified", {"fdc.80": ""}), "must not be empty"),
}


@pytest.mark.parametrize("case", sorted(WECS_BREAKAGES))
def test_wecs_dhm_rejects_bad_data(case: str) -> None:
    mutate, message = WECS_BREAKAGES[case]
    doc = copy.deepcopy(_raw(co.WECS_DHM_FILE))
    mutate(doc)
    with pytest.raises(CoefficientDataError, match=re.escape(message)):
        parse_wecs_dhm(doc)


MIP_BREAKAGES: dict[str, tuple[Mutator, str]] = {
    "schema_version": (_delete("schema_version"), "missing key 'schema_version'"),
    "region missing": (_delete("regions.7"), "regions 1..7"),
    "april": (_set("regions.2.ordinates.Apr", 1.01), "April = 1.00"),
    "negative": (_set("regions.2.ordinates.Jul", -1), "must be positive"),
    "month order": (_reverse_months("regions.5.ordinates"), "12 months"),
    "verified type": (_set("regions.1.verified", "yes"), "true or false"),
    "unverified needs note": (_set("regions.4.note", ""), "must not be empty"),
    "regions type": (_set("regions", []), "expected an object"),
}


@pytest.mark.parametrize("case", sorted(MIP_BREAKAGES))
def test_mip_rejects_bad_data(case: str) -> None:
    mutate, message = MIP_BREAKAGES[case]
    doc = copy.deepcopy(_raw(co.MIP_FILE))
    mutate(doc)
    with pytest.raises(CoefficientDataError, match=re.escape(message)):
        parse_mip(doc)


def test_rejects_non_object_document() -> None:
    with pytest.raises(CoefficientDataError, match="expected an object"):
        parse_wecs_dhm([])


def test_error_is_a_value_error() -> None:
    assert issubclass(CoefficientDataError, ValueError)


def test_read_json_reports_missing_and_invalid_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "broken.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("nepal_hydro.coefficients.resources.files", lambda _pkg: tmp_path)
    with pytest.raises(CoefficientDataError, match="data file not found"):
        co._read_json("absent.json")
    with pytest.raises(CoefficientDataError, match="invalid JSON"):
        co._read_json("broken.json")
