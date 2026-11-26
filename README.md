# nepal-hydro

[![CI](https://github.com/anishbhattarai-asm/nepalhydro/actions/workflows/ci.yml/badge.svg)](https://github.com/anishbhattarai-asm/nepalhydro/actions/workflows/ci.yml)

River flows for hydropower and irrigation design on **ungauged rivers in Nepal**, from a
few catchment numbers. A zero-dependency Python library (3.10+) and command-line tool
implementing the two standard methods, as published in Appendix A of the *Civil Works
Guidelines for Micro-Hydropower in Nepal*:

- **WECS/DHM (1990):** instantaneous flood peaks for any return period, the flow duration
  curve (Q0 to Q100), and long-term mean monthly flows.
- **MIP (1982):** a mean monthly hydrograph from one dry-season flow measurement.
- A side-by-side **WECS vs MIP** comparison.

Every published value of the guideline's Solu Khola worked example reproduces at the
guideline's own rounding; those values are the release tests.

> [!WARNING]
> **The outputs are estimates from regional regressions, not design values.** They do not
> replace site measurements, hydrological judgement or a design review. A licensed engineer
> must review every result before anything is designed or built on it. The software is
> provided under the MIT licence, without warranty of any kind.

## Install

```
pip install git+https://github.com/anishbhattarai-asm/nepalhydro
```

No runtime dependencies. `to_dataframe()` uses pandas if you have it installed.

## Quickstart: the Solu Khola example

```python
from nepal_hydro import Catchment, compare_monthly, mip, wecs_dhm

c = Catchment(
    name="Solu Khola",
    area_km2=330,  # total basin area A
    area_below_5000_km2=308.5,  # A5000
    area_below_3000_km2=97.7,  # A3000
    monsoon_wetness_index_mm=1500,
    mip_region=3,
)

floods = wecs_dhm.flood_peaks(c, return_periods=(2, 5, 10, 20, 50, 100))
assert round(floods[100].q_m3s) == 426

fdc = wecs_dhm.flow_duration(c)  # Q0, Q5, Q20, Q40, Q60, Q80, Q95, Q100
assert round(fdc.at(95), 2) == 2.03  # .at() interpolates between points in log-flow

monthly = wecs_dhm.monthly_flows(c)  # a Mapping "Jan".."Dec"
assert (round(monthly["Jul"], 2), round(monthly.annual_mean, 2)) == (43.86, 16.68)

# MIP: 2.8 m3/s measured in April, region 3
hydro = mip.monthly_hydrograph(c, measured_q_m3s=2.8, month=4)
assert round(hydro["Aug"], 2) == 70.00

table = compare_monthly(monthly, hydro)  # month -> (wecs_m3s, mip_m3s, ratio_mip_over_wecs)
assert round(table["Jul"].ratio_mip_over_wecs, 2) == 0.86
```

Each method uses only the `Catchment` fields its formulas need, so
`wecs_dhm.flood_peaks(Catchment(area_below_3000_km2=97.7))` works on its own; a missing
field raises `MissingInputError` naming it.

The guideline's published values, which the tests check:

| Output | Solu Khola (m3/s) |
| --- | --- |
| Floods Q2, Q5, Q10, Q20, Q50, Q100 | 106, 175, 228, 283, 362, 426 |
| Flow duration Q0, Q5, Q20, Q40, Q60, Q80, Q95, Q100 | 98.45, 59.33, 32.62, 9.47, 4.58, 3.00, 2.03, 1.78 |
| WECS/DHM monthly, Jan to Dec | 3.88, 3.30, 3.00, 3.17, 4.37, 15.17, 43.86, 52.45, 40.07, 17.59, 8.06, 5.24 (mean 16.68) |
| MIP monthly, Jan to Dec | 7.59, 5.26, 3.86, 2.80, 5.26, 8.76, 37.91, 70.00, 58.32, 29.18, 14.00, 10.50 |

[`examples/solu_khola.py`](examples/solu_khola.py) runs the whole example and prints it.

## Inputs

| Input | Field | Unit | Where it comes from |
| --- | --- | --- | --- |
| Total basin area | `area_km2` | km2 | Topographic map |
| Basin area below 5000 m | `area_below_5000_km2` | km2 | Topographic map |
| Basin area below 3000 m | `area_below_3000_km2` | km2 | Topographic map |
| Monsoon wetness index | `monsoon_wetness_index_mm` | mm | Guideline Figure A3 (isohyets) |
| MIP hydrological region | `mip_region` | 1 to 7 | Guideline Figure A2 |
| One dry-season flow measurement | `measured_q_m3s` (+ `month`, optional `day`) | m3/s | Site visit, Nov to Apr, no recent heavy rain |

Invalid geometry (for example A5000 > A) raises `ValueError`. Inputs that are valid but
outside what the method was built on still compute, and warn.

## Results, warnings and exports

Results are frozen dataclasses holding full-precision values; nothing is rounded except in
`repr`, and in exports when you pass `decimals=`. Every result carries `method`, `source`
(the guideline table and page) and `warnings`. Warnings are also issued through Python's
`warnings` module:

- `OutOfCalibrationRangeWarning`: total area outside 4 to 54 100 km2.
- `UnverifiedCoefficientWarning`: MIP region 4 (see Known caveats).
- `HydroWarning`: flood return periods above 100 years (extrapolated), a flow duration curve
  that rises with exceedance, a Q100 root below zero (Q100 set to 0), or an MIP measurement
  outside November to April.

Exports: `to_dict()` / `from_dict()`, `to_json()`, `to_csv(path_or_buffer)` and
`to_dataframe()`; `nepal_hydro.result_from_dict()` rebuilds any result from its dict.

## Command line

```
nepal-hydro flood   --a3000 97.7 --T 2 5 10 20 50 100
nepal-hydro fdc     --area 330 --a5000 308.5 --mwi 1500
nepal-hydro monthly --area 330 --a5000 308.5 --mwi 1500
nepal-hydro mip     --region 3 --q 2.8 --month 4
nepal-hydro all     --area 330 --a5000 308.5 --a3000 97.7 --mwi 1500 --region 3 --q 2.8 --month 4
```

- `--format table|json|csv` (default `table`) and `--decimals N` (default 2 for table and
  csv; JSON is full precision unless `--decimals` is given, so it rebuilds exactly with
  `result_from_dict`).
- `all` runs every method whose inputs are given and notes the rest on stderr
  (`skipped mip: needs --region, --q, --month`), so a desk study works before any field
  measurement. It fails only if nothing can run.
- Results go to stdout and warnings and notes to stderr only, so JSON and CSV output can be
  piped. All output is ASCII (`m3/s`, `km2`), so it works in Windows consoles using cp1252
  or cp437.
- Exit codes: `0` success, `1` invalid or missing input (a one-line message), `2` usage
  error.
- Windows PowerShell 5.1 (not PowerShell 7) adds a UTF-8 byte-order mark when it pipes
  text into another program, so a reader of piped JSON should decode with `utf-8-sig`:
  `json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))`.

## Methods

[docs/methods.md](docs/methods.md) has every equation, the interpolation rules, the
warnings and their causes. The full design spec is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md);
the coefficients live, with their sources, in
[`src/nepal_hydro/data/`](src/nepal_hydro/data/).

## Known caveats

Three items in the guideline scan could not be read cleanly. They are implemented
as the spec describes and are awaiting review against a clean printed copy:

- **WECS/DHM flow duration Q80 and Q100:** the forms are reconstructed from the
  Solu Khola worked example (the only forms that reproduce its Q80 = 3.00 and
  Q100 = 1.78). They do not warn on each call.
- **MIP region 4 ordinates:** separated from an interleaved scan (July and October
  both read 6.89). Using region 4 emits `UnverifiedCoefficientWarning`.

`nepal_hydro.coefficients.unverified()` lists every flagged item with its note.

The 1990 regressions also have limits of their own. Q20 to Q60 use total area while the
other flow duration points use A5000, and Q80, Q95 and Q100 (like the January to May monthly
flows) have no MWI term. So for basins mostly above 5000 m, or with an MWI below about
1000 mm, the curve can rise with exceedance. It is then kept as computed and warned about.

## Development

```
python -m venv .venv
# Linux/macOS: source .venv/bin/activate    Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest --cov                              # 95% coverage floor
pytest --hypothesis-profile=thorough      # property tests, 20 000 examples each
ruff check .
ruff format --check .
mypy
```

CI runs all of this on Ubuntu and Windows for Python 3.10 to 3.13, plus the CLI under
PowerShell 7 and Windows PowerShell 5.1.

## Licence

MIT. See [LICENSE](LICENSE).
