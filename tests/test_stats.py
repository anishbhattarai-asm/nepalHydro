"""The standard normal variate matches the guideline's Table A2."""

from __future__ import annotations

import math
from typing import Any

import pytest

from nepal_hydro._stats import standard_normal_variate

# Guideline Table A2 (return period in years -> S), as listed in the spec.
TABLE_A2 = {
    5: 0.842, 10: 1.282, 20: 1.645, 50: 2.054, 100: 2.326,
    200: 2.576, 500: 2.878, 1000: 3.090, 10000: 3.719,
}  # fmt: skip


@pytest.mark.parametrize(("t", "s"), sorted(TABLE_A2.items()))
def test_matches_table_a2_to_3dp(t: int, s: float) -> None:
    assert round(standard_normal_variate(t), 3) == s


def test_two_year_flood_is_the_median() -> None:
    assert standard_normal_variate(2) == pytest.approx(0.0, abs=1e-12)


def test_accepts_non_integer_periods() -> None:
    assert standard_normal_variate(2.5) > 0


@pytest.mark.parametrize("t", [1, 0.5, 0, -10, math.inf, math.nan])
def test_rejects_periods_that_are_not_above_one(t: float) -> None:
    with pytest.raises(ValueError, match="> 1"):
        standard_normal_variate(t)


@pytest.mark.parametrize("t", ["100", True, None])
def test_rejects_non_numbers(t: Any) -> None:
    with pytest.raises(TypeError):
        standard_normal_variate(t)
