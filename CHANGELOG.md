# Changelog

All notable changes to nepal-hydro are recorded here. Versions follow
[PEP 440](https://peps.python.org/pep-0440/); the format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0a1] - 2026-11-26

**Pre-release (alpha), pending engineer review.** Published to claim the
`nepal-hydro` name on PyPI. The methods reproduce every published value of the
guideline's Solu Khola worked example, but the following are still open and
may change coefficients or behaviour before 0.1.0:

- [#1](https://github.com/anishbhattarai-asm/nepalHydro/issues/1) Confirm the WECS/DHM flow duration Q80 and Q100 forms (reconstructed from the worked example)
- [#2](https://github.com/anishbhattarai-asm/nepalHydro/issues/2) Confirm the MIP region 4 ordinates (separated from an interleaved scan)
- [#3](https://github.com/anishbhattarai-asm/nepalHydro/issues/3) Confirm the MWI min/max from guideline Figure A3 (no MWI range is checked yet)
- [#4](https://github.com/anishbhattarai-asm/nepalHydro/issues/4) Check one real project's numbers against the library
- [#5](https://github.com/anishbhattarai-asm/nepalHydro/issues/5) Approve the README disclaimer wording

Install it with `pip install --pre nepal-hydro` (pip skips pre-releases
otherwise). The outputs are estimates; a licensed engineer must review them
before anything is built.

### Added

- WECS/DHM (1990): instantaneous flood peaks for 1 < T <= 10 000 years (log-normal
  fit through the Q2/Q100 anchors, with a warning beyond 100 years), the flow
  duration curve Q0 to Q100 with log-flow interpolation, and long-term mean
  monthly flows.
- MIP (1982): the mean monthly hydrograph from one dry-season measurement, with
  mid-month date interpolation (365-day year, Dec <-> Jan wrap, Feb 29 accepted).
- `compare_monthly`: WECS/DHM vs MIP month by month, with `ratio_mip_over_wecs`.
- `Catchment` validation; each method needs only the fields it uses
  (`MissingInputError` otherwise). Warnings for out-of-calibration areas,
  unverified coefficients, a non-monotonic flow duration curve and more, recorded
  on every result as well as issued through Python's `warnings`.
- Frozen, full-precision result types with `to_dict`/`from_dict`, `to_json`,
  `to_csv` and `to_dataframe`.
- The `nepal-hydro` CLI (`flood`, `fdc`, `monthly`, `mip`, `all`): table, JSON
  and CSV output, warnings on stderr only, ASCII output for Windows consoles,
  exit codes 0/1/2; `all` runs every method whose inputs are given.
- Zero runtime dependencies; Python 3.10 to 3.13; CI on Ubuntu and Windows,
  including the CLI under PowerShell 7 and Windows PowerShell 5.1.

[0.1.0a1]: https://github.com/anishbhattarai-asm/nepalHydro/releases/tag/v0.1.0a1
