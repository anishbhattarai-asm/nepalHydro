"""The guideline's Solu Khola worked example, end to end.

Run it from the repository root after `pip install -e .`:

    python examples/solu_khola.py

Inputs and published answers: Civil Works Guidelines for Micro-Hydropower in
Nepal, Appendix A, pages 148-149. The outputs are estimates; a licensed
engineer must review them before anything is built.
"""

from __future__ import annotations

from nepal_hydro import Catchment, compare_monthly, mip, wecs_dhm


def main() -> None:
    c = Catchment(
        name="Solu Khola",
        area_km2=330,
        area_below_5000_km2=308.5,
        area_below_3000_km2=97.7,
        monsoon_wetness_index_mm=1500,
        mip_region=3,
    )

    floods = wecs_dhm.flood_peaks(c, return_periods=(2, 5, 10, 20, 50, 100))
    print("Flood peaks (m3/s):")
    for t, estimate in floods.items():
        print(f"  Q{t:<4} {estimate.q_m3s:8.0f}")

    fdc = wecs_dhm.flow_duration(c)
    print("\nFlow duration curve (m3/s):")
    for p, q in fdc.points.items():
        print(f"  Q{p:<4} {q:8.2f}")
    print(f"  Q90 (interpolated) {fdc.at(90):.2f}")

    monthly = wecs_dhm.monthly_flows(c)
    hydro = mip.monthly_hydrograph(c, measured_q_m3s=2.8, month=4)
    table = compare_monthly(monthly, hydro)
    print("\nMean monthly flows (m3/s):")
    print(f"  {'Month':<12}{'WECS/DHM':>10}{'MIP':>10}{'MIP/WECS':>10}")
    for row in [*table.values(), table.annual]:
        name = "Annual mean" if row.month == "annual" else row.month
        r = row.ratio_mip_over_wecs
        ratio = "n/a" if r is None else f"{r:.2f}"
        print(f"  {name:<12}{row.wecs_m3s:10.2f}{row.mip_m3s:10.2f}{ratio:>10}")

    for result in (floods, fdc, monthly, hydro):
        for warning in result.warnings:
            print(f"warning: {warning}")


if __name__ == "__main__":
    main()
