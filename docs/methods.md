# Methods

The equations nepal-hydro implements, with their sources and known caveats. All
coefficients come from Appendix A (pages 146 to 149) of the *Civil Works Guidelines for
Micro-Hydropower in Nepal*. In the code they live in
[`src/nepal_hydro/data/wecs_dhm_1990.json`](../src/nepal_hydro/data/wecs_dhm_1990.json) and
[`src/nepal_hydro/data/mip_1982.json`](../src/nepal_hydro/data/mip_1982.json), each with its
source. The coefficient tables are printed in [ARCHITECTURE.md](ARCHITECTURE.md#method-reference),
and a test checks the data files against those tables value by value.

`ln` is the natural log. Flows are in m³/s, areas in km², MWI in mm.

| Symbol | Meaning | `Catchment` field |
| --- | --- | --- |
| A | total basin area | `area_km2` |
| A5000 | basin area below 5000 m | `area_below_5000_km2` |
| A3000 | basin area below 3000 m | `area_below_3000_km2` |
| MWI | monsoon wetness index | `monsoon_wetness_index_mm` |

The outputs are estimates. A licensed engineer must review them before anything is built.

## WECS/DHM (1990)

### Calibration range

The regressions were built on basins of 4 to 54 100 km² total area. When A is set and is
outside that range, every WECS/DHM method warns (`OutOfCalibrationRangeWarning`) and still
computes. When A is not set, a sub-area the method uses warns only above 54 100 km²: small
or zero sub-areas are normal (A3000 = 0 is why the formulas use A3000 + 1). The guideline
gives no MWI range, so MWI is only required to be positive.

### Instantaneous flood peaks (`wecs_dhm.flood_peaks`)

The 2-year and 100-year floods come from the area below 3000 m:

$$Q_2 = 1.8767\,(A_{3000} + 1)^{0.8783} \qquad Q_{100} = 14.630\,(A_{3000} + 1)^{0.7342}$$

Any other return period T follows a log-normal fit through those two anchors:

$$\sigma = \frac{\ln Q_{100} - \ln Q_2}{S_{100} - S_2} \qquad
\ln Q_T = \ln Q_2 + (S_T - S_2)\,\sigma \qquad S_T = \Phi^{-1}(1 - 1/T)$$

S is the standard normal variate, computed exactly (`statistics.NormalDist`) rather than
read from the guideline's Table A2; Table A2 is a test fixture instead. S₂ = 0 and
S₁₀₀ = 2.3263, so this is the guideline's `σ = ln(Q100/Q2) / 2.326`.

- Needs only A3000.
- T must satisfy 1 < T ≤ 10 000 years.
- T > 100 is an extrapolation beyond the upper anchor and warns (`HydroWarning`).

### Flow duration curve (`wecs_dhm.flow_duration`)

For P = 0, 5, 20, 40, 60, 80 and 95 percent of time exceeded:

$$\ln Q_P = C + a\,\ln X + b\,\ln \mathrm{MWI}$$

where X is A5000 + 1 for P = 0, 5, 80 and 95, and A for P = 20, 40 and 60; b = 0 for
P = 80 and 95. Q100 has its own form:

$$Q_{100} = \big(-0.09892 + 0.08149\,\sqrt{A_{5000} + 1}\big)^2$$

`FlowDurationCurve.at(p)` interpolates between those points linearly in ln Q, and raises
`ValueError` outside 0 to 100 (it never extrapolates). If one neighbour is 0 (see Q100
below), it interpolates linearly in Q instead.

**Caveats:**

- **Q80 and Q100 are reconstructed.** The scanned guideline garbles both lines: the Q80
  line repeats the area term where MWI would go, and the Q100 line drops the square root.
  The forms above are the only ones that reproduce the worked example (Q80 = 3.00,
  Q100 = 1.78). They do not warn on each call; `nepal_hydro.coefficients.unverified()`
  lists them.
- **Q100 for very small A5000.** Below A5000 ≈ 0.47 km², the root
  −0.09892 + 0.08149·√(A5000 + 1) is negative, and squaring it would invent a flow.
  Q100 is set to 0, with a `HydroWarning`.
- **The curve can rise with exceedance.** Q20, Q40 and Q60 use A while the other points use
  A5000, so a basin mostly above 5000 m can give Q20 > Q5. Q80, Q95 and Q100 have no MWI
  term, so a dry basin (MWI below about 1000 mm) can give Q80 > Q60. The low-MWI crossing is
  most likely a limit of the 1990 regressions in dry basins, not a reconstruction error:
  like the January to May monthly flows, the dry-season points were fitted on area alone.
  The values are kept as computed and a `HydroWarning` names each rising pair. Inside the
  calibration range the curve falls monotonically for A5000/A ≥ 0.7 and MWI ≥ 1000 mm
  (checked by the property tests).

### Long-term mean monthly flows (`wecs_dhm.monthly_flows`)

$$Q_{month} = C \cdot A^{a_1} \cdot (A_{5000} + 1)^{a_2} \cdot \mathrm{MWI}^{a_3}$$

An exponent of 0 drops its term. January to May depend on A5000 alone; June to December
add MWI. The annual mean is the arithmetic mean of the 12 months.

## MIP (1982): mean monthly hydrograph (`mip.monthly_hydrograph`)

1. Take one flow measurement between November and April (no recent heavy rain), and add
   any upstream abstractions to it.
2. Divide it by the region's ordinate for the measurement date. The result is the
   expected mean April flow.
3. Multiply the April flow by each month's ordinate (guideline Table A4, April = 1.00) to
   get the 12-month hydrograph.

$$Q_{Apr} = \frac{Q_m + Q_{abstracted}}{o_R(\text{date})} \qquad Q_{month} = Q_{Apr}\cdot o_R(month)$$

The hydrograph is exactly linear in the measurement and the abstractions.

**The ordinate on a date.** Without a day, o_R(date) is the measurement month's ordinate.
With a day, each ordinate is the value at the middle of its month, in a 365-day year
(February has 28 days). The measurement is placed at the middle of its day, and o_R is
interpolated linearly between the two mid-month points either side:

- The 16th of a 31-day month falls exactly on its month's ordinate. In a 30-day month,
  the middle falls between the 15th and the 16th.
- December and January are neighbours, so Dec 31 and Jan 1 both lie on the Dec–Jan
  segment, one day apart.
- February 29 is accepted, and placed where February 28 is.

**Warnings:**

- A measurement outside November to April still computes, with a `HydroWarning`.
- **Region 4 is unconfirmed.** The scan interleaves the region 3 and 4 columns; region 4
  was separated by pairing values, and its July and October both come out as 6.89, which
  looks suspicious. Using region 4 emits `UnverifiedCoefficientWarning` until the values
  are checked against the printed guideline.

## WECS vs MIP (`compare_monthly`)

Month by month, the WECS/DHM flow, the MIP flow and `ratio_mip_over_wecs` (MIP divided by
WECS/DHM, so above 1 means MIP gives more flow), plus the same for the annual means.

## Worked example

Solu Khola (guideline pages 148 to 149): A = 330 km², A5000 = 308.5 km², A3000 = 97.7 km²,
MWI = 1500 mm, MIP region 3, 2.8 m³/s measured in April. Every published value reproduces at
the guideline's own rounding; see `tests/test_golden_solu_khola.py` and the
[README](../README.md#quickstart-the-solu-khola-example).
