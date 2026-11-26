# nepal-hydro — Architecture & Design

Nov 26, 2026 · @Anish Bhattarai

## Overview

nepal-hydro is a zero-dependency Python library that turns a few catchment numbers into the river flows a Nepali hydropower or irrigation design needs. It implements the two standard methods for ungauged rivers in Nepal: WECS/DHM (1990) and MIP (1982), as published in Appendix A of the [Civil Works Guidelines for Micro-Hydropower in Nepal](https://samplecontents.library.ph/en-practical_action/Energy/Hydro%20power/civil_works_guidelines_for_micro_hydro/page146.html). Every formula in v0.1 has been checked against that guideline's Solu Khola worked example, and all of its published values reproduce exactly.

**Who uses it:** hydropower and irrigation consultants, IOE civil engineering students, AEPC micro-hydro designers, and developers building Nepali engineering tools. Today these engineers mostly redo these calculations by hand or in personal Excel sheets.

**v0.1 scope (the weekend build):**

- WECS/DHM instantaneous flood peaks for any return period
- WECS/DHM flow duration curve (Q0 to Q100)
- WECS/DHM long-term mean monthly flows and the annual mean
- MIP mean monthly hydrograph from one dry-season flow measurement
- A side-by-side WECS vs MIP comparison
- A CLI, plus results that export to dict, JSON and CSV

**Non-goals for v0.1:** delineating catchments from a DEM, rainfall-runoff models (SWAT, SPHY), and design sign-off. The outputs are estimates, and a licensed engineer must review them before anyone builds anything.

## Method reference

All coefficients below come from Appendix A, pages 146–149, of the micro-hydro civil works guideline. ln is the natural log. Flows are in m³/s, areas in km².

| Input | Symbol | Unit | Where the engineer gets it |
| --- | --- | --- | --- |
| Total basin area | A | km² | Topographic map |
| Basin area below 5000 m | A5000 | km² | Topographic map |
| Basin area below 3000 m | A3000 | km² | Topographic map |
| Monsoon wetness index | MWI | mm | Guideline Figure A3 (isohyet map) |
| MIP hydrological region | R | 1–7 | Guideline Figure A2 (region map) |
| One dry-season flow measurement | Qm | m³/s | Site visit, Nov–Apr, no recent heavy rain |

### WECS/DHM: instantaneous flood peaks

The 2-year and 100-year floods come from area below 3000 m:

```latex
Q_2 = 1.8767\,(A_{3000} + 1)^{0.8783} \qquad Q_{100} = 14.630\,(A_{3000} + 1)^{0.7342}
```

Any other return period T follows a log-normal fit through those two points. S is the standard normal variate, so S(100) = 2.326:

```latex
\sigma = \frac{\ln(Q_{100}/Q_2)}{2.326} \qquad Q_T = \exp\big(\ln Q_2 + S_T\,\sigma\big) \qquad S_T = \Phi^{-1}(1 - 1/T)
```

Compute S with `statistics.NormalDist().inv_cdf(1 - 1/T)` rather than hardcoding the guideline's Table A2. The table (5 yr = 0.842 … 10 000 yr = 3.719) becomes a test fixture instead.

### WECS/DHM: flow duration curve

Each exceedance level P has the form ln QP = C + a · ln(X) + b · ln(MWI):

| P (%) | C | a | X | b |
| --- | --- | --- | --- | --- |
| 0 | −3.5346 | 0.9398 | A5000 + 1 | 0.3739 |
| 5 | −3.4978 | 0.9814 | A5000 + 1 | 0.2670 |
| 20 | −5.4357 | 0.9824 | A | 0.4408 |
| 40 | −5.9543 | 1.0070 | A | 0.3231 |
| 60 | −6.4846 | 1.0004 | A | 0.3016 |
| 80 | −4.8508 | 1.0375 | A5000 + 1 | 0 |
| 95 | −5.4716 | 1.0776 | A5000 + 1 | 0 |

Q100 has its own form:

```latex
Q_{100\%} = \big(-0.09892 + 0.08149\,\sqrt{A_{5000} + 1}\big)^2
```

The scanned guideline garbles two of these. The Q80 line repeats the area term where MWI would go, and the Q100 line drops the square root. The forms above are the only ones that reproduce the worked example (Q80 = 3.00, Q100 = 1.78). Your engineer friend should confirm both against a clean copy.

### WECS/DHM: long-term mean monthly flows

```latex
Q_{month} = C \cdot A^{a_1} \cdot (A_{5000} + 1)^{a_2} \cdot MWI^{a_3}
```

An exponent of 0 drops that term. The annual mean is the arithmetic mean of the 12 months.

| Month | C | a1 | a2 | a3 |
| --- | --- | --- | --- | --- |
| Jan | 0.01423 | 0 | 0.9777 | 0 |
| Feb | 0.01219 | 0 | 0.9766 | 0 |
| Mar | 0.009988 | 0 | 0.9948 | 0 |
| Apr | 0.007974 | 0 | 1.0435 | 0 |
| May | 0.008434 | 0 | 1.0898 | 0 |
| Jun | 0.006943 | 0.9968 | 0 | 0.2610 |
| Jul | 0.02123 | 0 | 1.0093 | 0.2523 |
| Aug | 0.02548 | 0 | 0.9963 | 0.2620 |
| Sep | 0.01677 | 0 | 0.9894 | 0.2878 |
| Oct | 0.009724 | 0 | 0.9880 | 0.2508 |
| Nov | 0.001760 | 0.9605 | 0 | 0.3910 |
| Dec | 0.001485 | 0.9536 | 0 | 0.3607 |

### MIP: mean monthly hydrograph

1. Take one flow measurement between November and April, and add any upstream abstractions to it.
2. Divide it by the region's ordinate for the measurement month, interpolating if the reading was near a month boundary. The result is the expected mean April flow.
3. Multiply the April flow by each month's ordinate to get the 12-month hydrograph.

Non-dimensional ordinates (April = 1.00), guideline Table A4:

| Region | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2.40 | 1.80 | 1.30 | 1.00 | 2.30 | 6.00 | 14.50 | 25.00 | 16.50 | 8.00 | 4.10 | 3.10 |
| 2 | 2.24 | 1.70 | 1.33 | 1.00 | 1.21 | 7.27 | 18.18 | 27.27 | 20.91 | 9.09 | 3.94 | 3.03 |
| 3 | 2.71 | 1.88 | 1.38 | 1.00 | 1.88 | 3.13 | 13.54 | 25.00 | 20.83 | 10.42 | 5.00 | 3.75 |
| 4 (unconfirmed) | 2.59 | 1.88 | 1.38 | 1.00 | 2.19 | 3.75 | 6.89 | 27.27 | 20.91 | 6.89 | 5.00 | 3.44 |
| 5 | 2.42 | 1.82 | 1.36 | 1.00 | 0.91 | 2.73 | 11.21 | 13.94 | 10.00 | 6.52 | 4.55 | 3.33 |
| 6 | 2.03 | 1.62 | 1.27 | 1.00 | 2.57 | 6.08 | 24.32 | 33.78 | 27.03 | 6.08 | 3.38 | 2.57 |
| 7 | 3.30 | 2.20 | 1.40 | 1.00 | 3.50 | 6.00 | 14.00 | 35.00 | 24.00 | 12.00 | 7.50 | 5.00 |

Region 3 is confirmed by the worked example. The scan interleaves the region 3 and 4 columns, so I separated region 4 by pairing the values. Its July and October values both come out as 6.89, which looks suspicious. Verify region 4 against the printed guideline before release; until then, have the code raise `UnverifiedCoefficientWarning` for it.

## Package architecture

The design is pure functions over a validated `Catchment`. Coefficients live in JSON data files with their source attached, never as magic numbers in code. Every result carries the method name, the source citation and any warnings.

_(Diagram in the source doc: package architecture · inputs to outputs.)_

Inputs flow down through the two method modules into shared result types. The CLI, the Python API and compare.py all read those same results.

```text
nepal-hydro/
├── pyproject.toml              # hatchling, Python >=3.10, zero runtime deps
├── README.md                   # quickstart + Solu Khola example + disclaimer
├── LICENSE                     # MIT
├── src/nepal_hydro/
│   ├── __init__.py             # public API re-exports, __version__
│   ├── catchment.py            # Catchment dataclass + validation
│   ├── coefficients.py         # loads data/*.json into frozen dataclasses (cached)
│   ├── results.py              # FloodEstimate, FlowDurationCurve, MonthlyFlows (+ to_dict/to_json/to_csv)
│   ├── warnings.py             # HydroWarning, OutOfCalibrationRangeWarning, UnverifiedCoefficientWarning
│   ├── _stats.py               # standard normal variate via statistics.NormalDist
│   ├── methods/
│   │   ├── __init__.py
│   │   ├── wecs_dhm.py         # flood_peaks(), flow_duration(), monthly_flows()
│   │   └── mip.py              # monthly_hydrograph()
│   ├── compare.py              # compare_monthly(): WECS vs MIP side by side
│   ├── cli.py                  # `nepal-hydro` console script (argparse, no deps)
│   └── data/
│       ├── wecs_dhm_1990.json  # Tables A1–A3 + FDC coefficients, with source/page/verified flags
│       └── mip_1982.json       # Table A4 regional ordinates, per-region verified flag
├── tests/
│   ├── test_golden_solu_khola.py
│   ├── test_wecs_dhm.py
│   ├── test_mip.py
│   ├── test_catchment_validation.py
│   ├── test_coefficients_integrity.py
│   └── test_properties.py      # hypothesis: monotonicity, linear scaling
├── examples/solu_khola.py
└── docs/methods.md             # the equations, with sources and known caveats
```

**Public API (target for v0.1):**

```python
from nepal_hydro import Catchment, wecs_dhm, mip, compare_monthly

c = Catchment(
    name="Solu Khola",
    area_km2=330,
    area_below_5000_km2=308.5,
    area_below_3000_km2=97.7,
    monsoon_wetness_index_mm=1500,
    mip_region=3,
)

floods = wecs_dhm.flood_peaks(c, return_periods=(2, 5, 10, 20, 50, 100))
floods[100].q_m3s            # 426.x

fdc = wecs_dhm.flow_duration(c)              # default P = 0,5,20,40,60,80,95,100
fdc.at(95)                   # 2.03

monthly = wecs_dhm.monthly_flows(c)
monthly["Jul"], monthly.annual_mean          # 43.86, 16.68

hydro = mip.monthly_hydrograph(c, measured_q_m3s=2.8, month=4, day=None, abstractions_m3s=0.0)
hydro["Aug"]                 # 70.00

table = compare_monthly(monthly, hydro)      # rows: month, wecs, mip, ratio_mip_over_wecs
```

**CLI:**

```text
nepal-hydro flood   --a3000 97.7 --T 2 5 10 20 50 100
nepal-hydro fdc     --area 330 --a5000 308.5 --mwi 1500
nepal-hydro monthly --area 330 --a5000 308.5 --mwi 1500
nepal-hydro mip     --region 3 --q 2.8 --month 4
nepal-hydro all     --area 330 --a5000 308.5 --a3000 97.7 --mwi 1500 --region 3 --q 2.8 --month 4 --format csv
```

**Design rules for Claude Code to follow:**

- Units live in names (`_km2`, `_m3s`, `_mm`). The library handles SI only and never converts silently.
- Functions are pure: no globals, no I/O except loading coefficients once (`functools.cache`).
- Each result object keeps `method`, `source` (guideline + table + page) and `warnings: list[str]`, and also emits them through Python's `warnings` module.
- Don't round inside the library. Round only in `__repr__`, CLI output and exports.
- Type hints everywhere, `mypy --strict` clean, `ruff` for lint and format.
- Each data file carries a `schema_version` and is validated at load time.

## Data model and validation

Invalid geometry raises an exception. An input that is valid but outside the method's calibration range gives a warning, and the calculation still runs. A function receives only the fields it needs, so you can call `flood_peaks` with only `area_below_3000_km2` set.

| Catchment field | Type | Rule | On failure |
| --- | --- | --- | --- |
| `name` | str \| None | optional | — |
| `area_km2` | float \| None | > 0 | `ValueError` |
| `area_below_5000_km2` | float \| None | 0 ≤ A5000 ≤ A | `ValueError` |
| `area_below_3000_km2` | float \| None | 0 ≤ A3000 ≤ A5000 | `ValueError` |
| `monsoon_wetness_index_mm` | float \| None | > 0 | `ValueError` |
| `mip_region` | int \| None | 1–7 | `ValueError` |
| `area_km2` (when set) | — | outside 4–54 100 km² (regression range) | `OutOfCalibrationRangeWarning` |
| `area_below_5000_km2`, `area_below_3000_km2` (when `area_km2` is not set) | — | above 54 100 km²; small or zero values never warn (A3000 = 0 is valid) | `OutOfCalibrationRangeWarning` |
| missing field a method needs | — | name the field in the message | `MissingInputError` |

| MIP argument | Rule | On failure |
| --- | --- | --- |
| `measured_q_m3s` | > 0 | `ValueError` |
| `month` | 1–12; Nov–Apr is expected | outside Nov–Apr → `HydroWarning` |
| `day` | optional; if set, interpolate linearly between the mid-month ordinates of adjacent months (365-day year, wrapping Dec ↔ Jan); Feb 29 is treated as Feb 28 | invalid date → `ValueError` |
| `abstractions_m3s` | ≥ 0, added to the measurement | `ValueError` |
| region 4 | not yet confirmed | `UnverifiedCoefficientWarning` |

The 4–54 100 km² range is the span of total basin areas used to build the WECS/DHM regressions, per the [guideline](https://samplecontents.library.ph/en-practical_action/Energy/Hydro%20power/civil_works_guidelines_for_micro_hydro/page13.html), so it is checked against A. Sub-areas are checked, against the upper end only, when A is not given. The guideline gives no MWI range, so v0.1 checks only that MWI is positive.

**Result types (frozen dataclasses):**

- `FloodEstimate(return_period_yr, q_m3s)` and `FloodPeaks` (a mapping from T to estimate, plus `sigma_ln`, method, source, warnings)
- `FlowDurationCurve(points: dict[int, float])` with `.at(p)`. Between table points, interpolate in log-flow; never extrapolate past 0 or 100.
- `MonthlyFlows(by_month: dict[str, float])`, a `Mapping` with month-name keys "Jan"–"Dec" (so `dict(flows)` and `pd.Series(flows)` work), plus `.annual_mean` and `.to_list()`. Both WECS and MIP results use it, each with its own `method` field.
- Every result has `to_dict()`, `to_json()` and `to_csv(path_or_buffer)`, plus `to_dataframe()` if pandas happens to be installed.

**Coefficient JSON shape:**

```json
{
  "schema_version": 1,
  "method": "WECS/DHM 1990",
  "source": "Civil Works Guidelines for Micro-Hydropower in Nepal, Appendix A, p.146-147",
  "flood": {"2": {"alpha": 1.8767, "beta": 0.8783}, "100": {"alpha": 14.630, "beta": 0.7342}},
  "fdc": {"0": {"c": -3.5346, "a": 0.9398, "x": "A5000+1", "b": 0.3739}, "...": {}},
  "monthly": {"Jan": {"c": 0.01423, "a1": 0, "a2": 0.9777, "a3": 0}, "...": {}},
  "verified": {"fdc.80": "reconstructed from worked example", "fdc.100": "reconstructed from worked example"}
}
```

## Testing strategy

The release gate is the guideline's Solu Khola example: every published value must reproduce at the guideline's own rounding. My reconstruction of the formulas already does this in a scratch script.

**Golden inputs:** A = 330 km², A5000 = 308.5 km², A3000 = 97.7 km², MWI = 1500 mm, MIP region 3, measured 2.8 m³/s in April. Source: guideline [pages 148–149](https://samplecontents.library.ph/en-practical_action/Energy/Hydro%20power/civil_works_guidelines_for_micro_hydro/page148.html).

| Output | Golden values (m³/s) | Tolerance |
| --- | --- | --- |
| Flood Q2, Q5, Q10, Q20, Q50, Q100 | 106, 175, 228, 283, 362, 426 | round to integer |
| FDC Q0, Q5, Q20, Q40, Q60, Q80, Q95, Q100 | 98.45, 59.33, 32.62, 9.47, 4.58, 3.00, 2.03, 1.78 | round to 2 dp |
| WECS monthly Jan–Dec | 3.88, 3.30, 3.00, 3.17, 4.37, 15.17, 43.86, 52.45, 40.07, 17.59, 8.06, 5.24 | round to 2 dp |
| WECS annual mean | 16.68 | round to 2 dp |
| MIP monthly Jan–Dec | 7.59, 5.26, 3.86, 2.80, 5.26, 8.76, 37.91, 70.00, 58.32, 29.18, 14.00, 10.50 | round to 2 dp |

**Other test layers:**

- **Coefficient integrity:** 12 months in every table, April = 1.00 in every MIP region, every JSON entry has a source.
- **Normal variate:** `_stats` matches guideline Table A2 to 3 dp (5 yr 0.842, 10 yr 1.282, 20 yr 1.645, 50 yr 2.054, 100 yr 2.326, 200 yr 2.576, 500 yr 2.878, 1000 yr 3.090).
- **Properties (hypothesis):** flood grows with T; FDC falls as exceedance rises; the MIP hydrograph scales linearly with the measurement; growing any area never shrinks a flow.
- **Validation:** each rule in the data-model tables raises or warns exactly as listed.
- **CLI:** `nepal-hydro all … --format json` round-trips into the same result objects.
- **CI:** GitHub Actions on Python 3.10–3.13 running ruff, mypy --strict and pytest with at least 95% coverage.

**Engineer review checklist (for your friend):**

- [ ] Confirm the Q80 and Q100 FDC forms against a clean copy of the guideline
- [ ] Confirm MIP region 4 ordinates
- [ ] Check one real project's numbers, from a feasibility report he has, against the library
- [ ] Approve the README disclaimer wording

## Roadmap

The goal is v0.1.0 on PyPI by Sunday night, with the golden tests passing. Each later version adds one capability your engineer friend can review in a single sitting.

**The weekend:**

1. Saturday morning: scaffold, both coefficient JSON files, `Catchment` and its validation, and the warning classes.
2. Saturday afternoon: `wecs_dhm.flood_peaks`, `flow_duration` and `monthly_flows`, with the WECS golden tests passing.
3. Sunday morning: `mip.monthly_hydrograph` with day interpolation, `compare_monthly`, and the result exports.
4. Sunday afternoon: the CLI, README, `docs/methods.md`, CI, then TestPyPI and PyPI. Check that the name `nepal-hydro` is free on PyPI before you start.

**After v0.1:**

- **v0.2, more methods:** add the other empirical methods Nepali practice compares against, such as MHSP 1997, PCJ 1996 and Modified MIP ([comparison study](https://nepjol.info/index.php/tgb/article/download/55425/41375/164508)). Look up each one's equations from its original source.
- **v0.3, location lookup:** derive the MIP region and MWI from latitude and longitude, using GeoJSON digitized from guideline Figures A2 and A3. Your friend can do the digitizing in QGIS.
- **v0.4, catchment from a DEM:** an optional `[geo]` extra that takes an outlet point and SRTM data and returns A, A3000 and A5000, so engineers no longer measure them on paper maps.
- **v0.5, micro-hydro sizing:** design flow at a chosen exceedance, gross power from P = ρgQHη, penstock sizing, and turbine type by specific speed, following AEPC practice.
- **v1.0, web calculator:** a React/Vite front end running the library in the browser via Pyodide, plus a printable PDF report.

## Claude Code kickoff prompt

First export this doc as Markdown and save it in the new repo as `docs/ARCHITECTURE.md`, so Claude Code reads the exact tables instead of retyped ones. Then paste the prompt below.

```text
You are building nepal-hydro v0.1.0, a zero-dependency Python (>=3.10) library implementing the WECS/DHM (1990) and MIP (1982) hydrology methods for ungauged rivers in Nepal.

The complete spec is docs/ARCHITECTURE.md. Read all of it before writing any code. It is the source of truth for the repo layout, the public API, the coefficient tables, the validation rules and the golden test values.

Hard rules:
1. Copy coefficients from the spec into src/nepal_hydro/data/*.json exactly as written. Never put a coefficient as a literal in Python code.
2. The Solu Khola golden tests are the acceptance criteria. If one fails, fix the code. Never edit golden values, tolerances or coefficients to make a test pass. If you think a spec value is wrong, stop and tell me.
3. MIP region 4 and the FDC Q80/Q100 forms are flagged in the spec. Implement them as written, and emit UnverifiedCoefficientWarning for region 4.
4. Zero runtime dependencies. Dev dependencies only: pytest, hypothesis, ruff, mypy.
5. Keep units in names (_km2, _m3s, _mm). Write pure functions, and round only in repr, CLI output and exports.
6. I'm on Windows with PowerShell, so give PowerShell-compatible commands.

Work in this order. After each step, run the tests, show me the output, and wait for my OK:
Step 1: pyproject.toml (hatchling, src layout, console script `nepal-hydro`), package skeleton, the data JSON files, coefficients.py with load-time validation, and test_coefficients_integrity.py.
Step 2: catchment.py, warnings.py, _stats.py, and test_catchment_validation.py.
Step 3: methods/wecs_dhm.py and results.py, with the WECS parts of test_golden_solu_khola.py passing.
Step 4: methods/mip.py (including day interpolation), compare.py, and the MIP golden tests passing.
Step 5: test_properties.py with hypothesis.
Step 6: cli.py and its tests.
Step 7: README (quickstart, Solu Khola example, the disclaimer that outputs need review by a licensed engineer), docs/methods.md, examples/solu_khola.py, and a GitHub Actions workflow (ruff, mypy --strict, pytest --cov with a 95% floor, Python 3.10 to 3.13).

Do not start v0.2+ features.
```
