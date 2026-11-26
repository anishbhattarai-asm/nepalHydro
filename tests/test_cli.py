"""The nepal-hydro CLI: formats, streams, exit codes, ASCII output, JSON round-trip."""

from __future__ import annotations

import csv
import io
import json
import os
import runpy
import subprocess
import sys
import warnings
from typing import Any

import pytest

from nepal_hydro import (
    Catchment,
    FloodPeaks,
    FlowDurationCurve,
    MonthlyComparison,
    MonthlyFlows,
    compare_monthly,
    mip,
    result_from_dict,
    wecs_dhm,
)
from nepal_hydro.cli import ascii_text, main

SOLU = ["--area", "330", "--a5000", "308.5", "--a3000", "97.7", "--mwi", "1500"]
MEASUREMENT = ["--region", "3", "--q", "2.8", "--month", "4"]
ALL = ["all", *SOLU, *MEASUREMENT]


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_usage(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    with pytest.raises(SystemExit) as info:
        main(list(argv))
    return int(info.value.code or 0), capsys.readouterr().err


@pytest.fixture
def library(solu_khola: Catchment) -> dict[str, Any]:
    """What the library itself returns for the CLI's Solu Khola arguments."""
    wecs = wecs_dhm.monthly_flows(solu_khola)
    hydro = mip.monthly_hydrograph(solu_khola, measured_q_m3s=2.8, month=4)
    return {
        "flood_peaks": wecs_dhm.flood_peaks(solu_khola),
        "flow_duration": wecs_dhm.flow_duration(solu_khola),
        "wecs_monthly": wecs,
        "mip_monthly": hydro,
        "comparison": compare_monthly(wecs, hydro),
    }


# ---------------------------------------------------------------- table


def test_table_is_the_default(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, *ALL)
    assert (code, err) == (0, "")
    for text in ("Flood peaks: WECS/DHM 1990", "Flow duration curve", "WECS/DHM vs MIP",
                 "Q (m3/s)", "426.06", "Q95", "2.03", "Annual mean", "16.68", "70.00",
                 "licensed engineer"):  # fmt: skip
        assert text in out
    assert out.isascii()


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["flood", "--a3000", "97.7"], ["T (yr)", "426.06", "105.93"]),
        (["fdc", "--area", "330", "--a5000", "308.5", "--mwi", "1500"], ["Q80", "3.00"]),
        (["monthly", "--area", "330", "--a5000", "308.5", "--mwi", "1500"], ["Jul", "43.86"]),
        (["mip", *MEASUREMENT], ["Aug", "70.00", "MIP 1982"]),
    ],
)
def test_each_command_needs_only_its_inputs(
    capsys: pytest.CaptureFixture[str], argv: list[str], expected: list[str]
) -> None:
    code, out, err = run(capsys, *argv)
    assert (code, err) == (0, "")
    for text in expected:
        assert text in out


def test_decimals(capsys: pytest.CaptureFixture[str], library: dict[str, Any]) -> None:
    q100 = library["flood_peaks"][100].q_m3s
    _, out, _ = run(capsys, "flood", "--a3000", "97.7", "--decimals", "0")
    assert f" {q100:.0f}\n" in out
    _, out, _ = run(capsys, "flood", "--a3000", "97.7", "--decimals", "4")
    assert f" {q100:.4f}\n" in out


def test_return_periods(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "flood", "--a3000", "97.7", "--T", "2", "2.33", "100")
    assert code == 0
    rows = [line.split()[0] for line in out.splitlines() if line[:1].isdigit()]
    assert rows == ["2", "2.33", "100"]


# ----------------------------------------------------------------- json


def test_all_json_round_trips_into_the_same_results(
    capsys: pytest.CaptureFixture[str], library: dict[str, Any]
) -> None:
    code, out, err = run(capsys, *ALL, "--format", "json")
    assert (code, err) == (0, "")
    data = json.loads(out)
    assert list(data) == list(library)
    for name, value in data.items():
        assert result_from_dict(value) == library[name], name
    types = {name: type(result_from_dict(v)) for name, v in data.items()}
    assert types == {
        "flood_peaks": FloodPeaks, "flow_duration": FlowDurationCurve,
        "wecs_monthly": MonthlyFlows, "mip_monthly": MonthlyFlows,
        "comparison": MonthlyComparison,
    }  # fmt: skip


def test_single_command_json_is_one_result(
    capsys: pytest.CaptureFixture[str], library: dict[str, Any]
) -> None:
    _, out, _ = run(capsys, "fdc", *SOLU, "--format", "json")
    assert result_from_dict(json.loads(out)) == library["flow_duration"]


def test_json_rounds_only_when_decimals_is_given(capsys: pytest.CaptureFixture[str]) -> None:
    _, out, _ = run(capsys, "monthly", *SOLU, "--format", "json", "--decimals", "2")
    data = json.loads(out)
    assert data["by_month"]["Jul"] == 43.86
    assert data["annual_mean"] == 16.68


# ------------------------------------------------------------------ csv


def test_single_command_csv(capsys: pytest.CaptureFixture[str], library: dict[str, Any]) -> None:
    _, out, _ = run(capsys, "fdc", *SOLU, "--format", "csv")
    assert out == library["flow_duration"].to_csv(decimals=2)
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == ["exceedance_pct", "q_m3s"]
    assert rows[-1] == ["100", "1.78"]


def test_all_csv_has_one_section_per_result(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, *ALL, "--format", "csv")
    assert code == 0
    sections = [line for line in out.splitlines() if line.startswith("# ")]
    assert sections == ["# flood_peaks", "# flow_duration", "# wecs_monthly", "# mip_monthly",
                        "# comparison"]  # fmt: skip
    assert "month,wecs_m3s,mip_m3s,ratio_mip_over_wecs" in out
    assert "Jul,43.86,37.91,0.86" in out


# ------------------------------------------------- warnings go to stderr


def test_warnings_go_to_stderr_and_json_stays_clean(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["all", "--area", "2", "--a5000", "2", "--a3000", "1", "--mwi", "1500",
            "--region", "4", "--q", "1", "--month", "7", "--T", "2", "500",
            "--format", "json"]  # fmt: skip
    code, out, err = run(capsys, *argv)
    assert code == 0
    data = json.loads(out)  # stdout is pure JSON
    lines = err.splitlines()
    assert all(line.startswith("nepal-hydro: warning: ") for line in lines)
    joined = "\n".join(lines)
    for text in ("outside the 4 to 54100 km2 range", "region 4", "between November and April",
                 "extrapolated beyond the 2/100-yr anchors"):  # fmt: skip
        assert text in joined
    assert len(lines) == len(set(lines))  # each warning printed once
    assert err.isascii()
    assert "km2" in err
    assert "km²" not in err
    # The warnings are still inside the results for anyone reading the JSON.
    assert data["mip_monthly"]["warnings"]


def test_no_python_warnings_leak(capsys: pytest.CaptureFixture[str]) -> None:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        run(capsys, "flood", "--area", "2", "--a3000", "1")
    assert record == []


def test_table_warnings_also_go_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "mip", "--region", "4", "--q", "1", "--month", "4")
    assert code == 0
    assert "warning" not in out
    assert "UnverifiedCoefficient" not in err
    assert "region 4" in err


# --------------------------------------------- `all` runs what it can


def _notes(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("nepal-hydro: note: ")]


def test_desk_study_without_a_measurement(
    capsys: pytest.CaptureFixture[str], library: dict[str, Any]
) -> None:
    code, out, err = run(capsys, "all", *SOLU, "--format", "json")
    assert code == 0
    data = json.loads(out)
    assert list(data) == ["flood_peaks", "flow_duration", "wecs_monthly"]
    for name, value in data.items():
        assert result_from_dict(value) == library[name]
    assert _notes(err) == [
        "nepal-hydro: note: skipped mip: needs --region, --q, --month",
        "nepal-hydro: note: skipped compare: needs the monthly and mip results",
    ]


def test_only_floods(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "all", "--a3000", "97.7", "--format", "json")
    assert code == 0
    assert list(json.loads(out)) == ["flood_peaks"]  # still keyed by section
    assert _notes(err) == [
        "nepal-hydro: note: skipped fdc: needs --area, --a5000, --mwi",
        "nepal-hydro: note: skipped monthly: needs --area, --a5000, --mwi",
        "nepal-hydro: note: skipped mip: needs --region, --q, --month",
        "nepal-hydro: note: skipped compare: needs the monthly and mip results",
    ]


def test_only_the_measurement(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "all", *MEASUREMENT, "--format", "csv")
    assert code == 0
    assert [line for line in out.splitlines() if line.startswith("# ")] == ["# mip_monthly"]
    assert "nepal-hydro: note: skipped flood: needs --a3000" in err
    assert "error" not in err


def test_skip_notes_list_only_what_is_missing(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, "all", "--a3000", "97.7", "--region", "3", "--q", "2.8")
    assert code == 0
    assert "nepal-hydro: note: skipped mip: needs --month" in _notes(err)


@pytest.mark.parametrize("argv", [["all"], ["all", "--region", "3", "--q", "2.8"]])
def test_all_with_nothing_to_run_exits_1(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, out, err = run(capsys, *argv)
    assert code == 1
    assert out == ""
    assert err.splitlines()[-1] == (
        "nepal-hydro: error: nothing to run: give the inputs of at least one method"
    )
    assert len(_notes(err)) == 5


def test_all_still_rejects_invalid_input(capsys: pytest.CaptureFixture[str]) -> None:
    # A skipped method is about missing inputs; a bad value is still an error.
    code, out, err = run(capsys, "all", "--a3000", "97.7", "--region", "9", "--q", "1",
                         "--month", "4")  # fmt: skip
    assert (code, out) == (1, "")
    assert "mip_region must be 1 to 7" in err


def test_notes_come_before_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    _, out, err = run(capsys, "all", "--a3000", "60000", "--format", "json")
    kinds = [line.split(":")[1].strip() for line in err.splitlines()]
    assert kinds == ["note"] * 4 + ["warning"]
    json.loads(out)


# ------------------------------------------------------------ exit codes


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["mip", "--region", "9", "--q", "2.8", "--month", "4"], "mip_region must be 1 to 7"),
        (["mip", "--region", "3", "--q", "-1", "--month", "4"], "measured_q_m3s"),
        (["mip", "--region", "3", "--q", "1", "--month", "2", "--day", "30"], "invalid date"),
        (["mip", "--region", "3", "--month", "4"], "mip needs --q"),
        (["mip", "--q", "1"], "mip needs --region, --month"),
        (["flood", "--area", "330"], "area_below_3000_km2 (set --a3000)"),
        (["fdc", "--area", "330"],
         "area_below_5000_km2, monsoon_wetness_index_mm (set --a5000, --mwi)"),
        (["flood", "--a3000", "97.7", "--T", "1"], "> 1"),
        (["flood", "--a3000", "97.7", "--T", "20000"], "at most 10000"),
        (["monthly", "--area", "100", "--a5000", "200", "--mwi", "1500"], "cannot exceed"),
        (["flood", "--a3000", "nan"], "must be finite"),
    ],
)  # fmt: skip
def test_invalid_input_exits_1_with_the_message(
    capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    code, out, err = run(capsys, *argv)
    assert code == 1
    assert out == ""
    assert err.startswith("nepal-hydro: error: ")
    assert message in err
    assert "Traceback" not in err
    assert err.count("\n") == 1


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["nope"],
        ["flood", "--a3000", "big"],
        ["flood", "--a3000", "97.7", "--format", "xml"],
        ["flood", "--a3000", "97.7", "--decimals", "-1"],
        ["flood", "--a3000", "97.7", "--decimals", "two"],
        ["mip", "--region", "three"],
        ["flood", "--bogus"],
    ],
)
def test_usage_errors_exit_2(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    code, err = run_usage(capsys, *argv)
    assert code == 2
    assert "usage: nepal-hydro" in err


def test_help_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run_usage(capsys, "--help")
    assert code == 0
    code, _ = run_usage(capsys, "--version")
    assert code == 0


# ------------------------------------------------------- ASCII / encodings


def test_ascii_text() -> None:
    assert ascii_text("4\u201354 100 km\u00b2, 2.8 m\u00b3/s") == "4-54 100 km2, 2.8 m3/s"
    assert ascii_text("नेपाल") == "?????"


@pytest.mark.parametrize("encoding", ["cp1252", "cp437", "ascii"])
@pytest.mark.parametrize("fmt", ["table", "json", "csv"])
def test_runs_on_narrow_windows_encodings(encoding: str, fmt: str) -> None:
    # Region 4 and an out-of-range area put warnings on stderr too.
    argv = ["all", "--area", "2", "--a5000", "2", "--a3000", "1", "--mwi", "1500",
            "--region", "4", "--q", "1", "--month", "4", "--format", fmt]  # fmt: skip
    env = {**os.environ, "PYTHONIOENCODING": encoding, "PYTHONUTF8": "0"}
    proc = subprocess.run(
        [sys.executable, "-m", "nepal_hydro", *argv], capture_output=True, env=env, check=False
    )
    assert proc.returncode == 0, proc.stderr.decode(encoding, "replace")
    out, err = proc.stdout.decode(encoding), proc.stderr.decode(encoding)
    assert out.isascii()
    assert err.isascii()
    assert "warning" in err
    assert "km2" in err
    if fmt == "table":
        assert "m3/s" in out
    if fmt == "json":
        assert set(json.loads(out)) >= {"flood_peaks", "comparison"}


def test_python_dash_m(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["nepal-hydro", "flood", "--a3000", "97.7"])
    with pytest.raises(SystemExit) as info:
        runpy.run_module("nepal_hydro", run_name="__main__")
    assert info.value.code == 0
    assert "426.06" in capsys.readouterr().out
