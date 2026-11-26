from __future__ import annotations

import pytest

from nepal_hydro import Catchment


@pytest.fixture
def solu_khola() -> Catchment:
    """The guideline's worked example (pages 148-149)."""
    return Catchment(
        name="Solu Khola",
        area_km2=330,
        area_below_5000_km2=308.5,
        area_below_3000_km2=97.7,
        monsoon_wetness_index_mm=1500,
        mip_region=3,
    )
