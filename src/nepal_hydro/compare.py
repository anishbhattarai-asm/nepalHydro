"""WECS/DHM vs MIP monthly flows, side by side."""

from __future__ import annotations

from nepal_hydro.results import MonthlyComparison, MonthlyFlows

__all__ = ["compare_monthly"]


def compare_monthly(wecs: MonthlyFlows, mip: MonthlyFlows) -> MonthlyComparison:
    """Rows of month, WECS flow, MIP flow and ratio (MIP / WECS), plus the annual means.

    The comparison carries both results' warnings, and both sources.
    """
    for name, flows in (("wecs", wecs), ("mip", mip)):
        if not isinstance(flows, MonthlyFlows):
            raise TypeError(f"{name} must be a MonthlyFlows result, got {type(flows).__name__}")
    sources = list(dict.fromkeys((wecs.source, mip.source)))
    return MonthlyComparison(
        wecs=wecs,
        mip=mip,
        method=f"{wecs.method} vs {mip.method}",
        source="; ".join(sources),
        warnings=(*wecs.warnings, *mip.warnings),
    )
