"""The ``nepal-hydro`` console script.

Results go to stdout and warnings to stderr only, so ``--format json`` and
``--format csv`` output can be piped. Every character written is ASCII
("m3/s", "km2"), because Windows consoles using cp1252 or cp437 cannot all
encode "³".

Exit codes: 0 success, 1 invalid input (the message, no traceback), 2 usage
error (from argparse).
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections.abc import Sequence
from typing import Any, TextIO

from nepal_hydro import __version__
from nepal_hydro.catchment import Catchment, MissingInputError
from nepal_hydro.compare import compare_monthly
from nepal_hydro.methods import mip, wecs_dhm
from nepal_hydro.results import (
    AnyResult,
    FloodPeaks,
    FlowDurationCurve,
    MonthlyComparison,
    MonthlyFlows,
)

__all__ = ["main"]

PROG = "nepal-hydro"
DISCLAIMER = "Estimates only: a licensed engineer must review them before anything is built."

# Catchment field -> the CLI flag that sets it (for error messages).
FLAGS = {
    "area_km2": "--area",
    "area_below_5000_km2": "--a5000",
    "area_below_3000_km2": "--a3000",
    "monsoon_wetness_index_mm": "--mwi",
    "mip_region": "--region",
}

_ASCII = str.maketrans(
    {"\u00b2": "2", "\u00b3": "3", "\u2013": "-", "\u2014": "-", "\u2194": "<->",
     "\u00d7": "x", "\u00b5": "u"}
)  # fmt: skip


def ascii_text(text: str) -> str:
    """``text`` with units spelled in ASCII, and anything else non-ASCII replaced."""
    return text.translate(_ASCII).encode("ascii", "replace").decode("ascii")


# --------------------------------------------------------------------- parser


def _decimals(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if not 0 <= value <= 15:
        raise argparse.ArgumentTypeError("must be 0 to 15")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="WECS/DHM (1990) and MIP (1982) hydrology for ungauged rivers in Nepal. "
        + DISCLAIMER,
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")

    output = argparse.ArgumentParser(add_help=False)
    group = output.add_argument_group("output")
    group.add_argument("--format", choices=("table", "json", "csv"), default="table",
                       help="output format (default: table)")  # fmt: skip
    group.add_argument(
        "--decimals",
        type=_decimals,
        default=None,
        metavar="N",
        help="decimal places (default: 2 for table and csv; json is full precision "
        "unless N is given)",
    )

    catchment = argparse.ArgumentParser(add_help=False)
    group = catchment.add_argument_group("catchment (set what the method needs)")
    group.add_argument("--area", type=float, metavar="KM2", help="total basin area A, km2")
    group.add_argument("--a5000", type=float, metavar="KM2", help="basin area below 5000 m, km2")
    group.add_argument("--a3000", type=float, metavar="KM2", help="basin area below 3000 m, km2")
    group.add_argument("--mwi", type=float, metavar="MM", help="monsoon wetness index, mm")

    floods = argparse.ArgumentParser(add_help=False)
    floods.add_argument(
        "--T",
        dest="return_periods",
        type=float,
        nargs="+",
        default=list(wecs_dhm.DEFAULT_RETURN_PERIODS),
        metavar="YR",
        help="return periods in years, 1 < T <= 10000 (default: 2 5 10 20 50 100)",
    )

    measurement = argparse.ArgumentParser(add_help=False)
    group = measurement.add_argument_group("MIP measurement")
    group.add_argument("--region", type=int, metavar="1-7", help="MIP hydrological region")
    group.add_argument("--q", type=float, metavar="M3S", help="measured flow, m3/s")
    group.add_argument("--month", type=int, metavar="1-12", help="month of the measurement")
    group.add_argument("--day", type=int, metavar="D", help="day of the measurement (optional)")
    group.add_argument("--abstractions", type=float, default=0.0, metavar="M3S",
                       help="upstream abstractions added to the measurement, m3/s")  # fmt: skip

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    common = [catchment, output]
    sub.add_parser("flood", parents=[*common, floods], help="WECS/DHM flood peaks")
    sub.add_parser("fdc", parents=common, help="WECS/DHM flow duration curve")
    sub.add_parser("monthly", parents=common, help="WECS/DHM mean monthly flows")
    sub.add_parser("mip", parents=[measurement, output], help="MIP mean monthly hydrograph")
    sub.add_parser(
        "all", parents=[*common, measurement, floods], help="everything, plus WECS vs MIP"
    )
    return parser


# -------------------------------------------------------------------- running


def _catchment(args: argparse.Namespace) -> Catchment:
    return Catchment(
        area_km2=getattr(args, "area", None),
        area_below_5000_km2=getattr(args, "a5000", None),
        area_below_3000_km2=getattr(args, "a3000", None),
        monsoon_wetness_index_mm=getattr(args, "mwi", None),
        mip_region=getattr(args, "region", None),
    )


def _periods(args: argparse.Namespace) -> list[float]:
    # "--T 100" arrives as 100.0; keep whole years as ints so they print as "100".
    # (float() first: the defaults are ints, and int.is_integer() needs Python 3.12.)
    periods = [float(t) for t in args.return_periods]
    return [int(t) if t.is_integer() else t for t in periods]


def _mip(c: Catchment, args: argparse.Namespace) -> MonthlyFlows:
    if args.q is None or args.month is None:
        missing = [flag for flag, v in (("--q", args.q), ("--month", args.month)) if v is None]
        raise ValueError(f"the MIP hydrograph needs {' and '.join(missing)}")
    return mip.monthly_hydrograph(
        c, measured_q_m3s=args.q, month=args.month, day=args.day,
        abstractions_m3s=args.abstractions,
    )  # fmt: skip


def _run(args: argparse.Namespace) -> dict[str, AnyResult]:
    """The results for the command, by section name."""
    c = _catchment(args)
    if args.command == "flood":
        return {"flood_peaks": wecs_dhm.flood_peaks(c, _periods(args))}
    if args.command == "fdc":
        return {"flow_duration": wecs_dhm.flow_duration(c)}
    if args.command == "monthly":
        return {"wecs_monthly": wecs_dhm.monthly_flows(c)}
    if args.command == "mip":
        return {"mip_monthly": _mip(c, args)}
    wecs = wecs_dhm.monthly_flows(c)
    hydro = _mip(c, args)
    return {
        "flood_peaks": wecs_dhm.flood_peaks(c, _periods(args)),
        "flow_duration": wecs_dhm.flow_duration(c),
        "wecs_monthly": wecs,
        "mip_monthly": hydro,
        "comparison": compare_monthly(wecs, hydro),
    }


# ------------------------------------------------------------------ rendering


def _num(value: float | None, decimals: int) -> str:
    return "n/a" if value is None else f"{value:.{decimals}f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    first = [
        h.ljust(w) if i == 0 else h.rjust(w)
        for i, (h, w) in enumerate(zip(headers, widths, strict=True))
    ]
    lines = ["  ".join(first), "  ".join("-" * w for w in widths)]
    for row in rows:
        cells = [
            c.ljust(w) if i == 0 else c.rjust(w)
            for i, (c, w) in enumerate(zip(row, widths, strict=True))
        ]
        lines.append("  ".join(cells))
    return lines


TITLES = {
    "flood_peaks": "Flood peaks",
    "flow_duration": "Flow duration curve",
    "wecs_monthly": "Mean monthly flows (WECS/DHM)",
    "mip_monthly": "Mean monthly flows (MIP)",
    "comparison": "WECS/DHM vs MIP",
}


def _render_table(name: str, result: AnyResult, d: int) -> list[str]:
    lines = [f"{TITLES[name]}: {result.method}", f"Source: {result.source}", ""]
    if isinstance(result, FloodPeaks):
        rows = [[f"{e.return_period_yr:g}", _num(e.q_m3s, d)] for e in result.values()]
        lines += _table(["T (yr)", "Q (m3/s)"], rows)
    elif isinstance(result, FlowDurationCurve):
        rows = [[f"Q{p}", _num(q, d)] for p, q in result.points.items()]
        lines += _table(["Exceedance", "Q (m3/s)"], rows)
    elif isinstance(result, MonthlyFlows):
        rows = [[m, _num(q, d)] for m, q in result.items()]
        rows.append(["Annual mean", _num(result.annual_mean, d)])
        lines += _table(["Month", "Q (m3/s)"], rows)
    else:
        assert isinstance(result, MonthlyComparison)
        rows = [
            [r.month if r.month != "annual" else "Annual mean", _num(r.wecs_m3s, d),
             _num(r.mip_m3s, d), _num(r.ratio_mip_over_wecs, d)]
            for r in [*result.values(), result.annual]
        ]  # fmt: skip
        lines += _table(["Month", "WECS (m3/s)", "MIP (m3/s)", "MIP/WECS"], rows)
    return lines


def _render(results: dict[str, AnyResult], fmt: str, decimals: int | None) -> str:
    if fmt == "json":
        data = {name: json.loads(r.to_json(decimals=decimals)) for name, r in results.items()}
        payload: Any = next(iter(data.values())) if len(data) == 1 else data
        return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
    d = 2 if decimals is None else decimals
    if fmt == "csv":
        blocks = []
        for name, result in results.items():
            text = result.to_csv(decimals=d)
            assert text is not None
            blocks.append(text if len(results) == 1 else f"# {name}\n{text}")
        return "\n".join(blocks)
    sections = ["\n".join(_render_table(name, r, d)) for name, r in results.items()]
    return "\n\n".join(sections) + f"\n\n{DISCLAIMER}\n"


# ----------------------------------------------------------------------- main


def _missing_message(err: MissingInputError) -> str:
    flags = ", ".join(FLAGS.get(f, f) for f in err.missing)
    return f"{err} (set {flags})"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; returns the exit code (argparse exits with 2 on usage errors)."""
    args = _build_parser().parse_args(argv)
    out: TextIO = sys.stdout
    err: TextIO = sys.stderr
    try:
        with warnings.catch_warnings():
            # Results record their own warnings; print those once, cleanly, below.
            warnings.simplefilter("ignore")
            results = _run(args)
    except MissingInputError as exc:
        print(ascii_text(f"{PROG}: error: {_missing_message(exc)}"), file=err)
        return 1
    except (ValueError, TypeError) as exc:
        print(ascii_text(f"{PROG}: error: {exc}"), file=err)
        return 1

    seen: dict[str, None] = {}
    for result in results.values():
        seen.update(dict.fromkeys(result.warnings))
    for message in seen:
        print(ascii_text(f"{PROG}: warning: {message}"), file=err)
    out.write(ascii_text(_render(results, args.format, args.decimals)))
    out.flush()
    return 0
