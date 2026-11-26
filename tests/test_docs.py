"""The README, docs/methods.md and the example stay true to the code."""

from __future__ import annotations

import re
import runpy
import warnings
from pathlib import Path

import pytest

from nepal_hydro.coefficients import FdcSquaredSqrt, load_wecs_dhm

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
METHODS = (ROOT / "docs" / "methods.md").read_text(encoding="utf-8")


def test_readme_quickstart_runs() -> None:
    blocks = re.findall(r"```python\n(.*?)```", README, flags=re.S)
    assert blocks, "README has no python block"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for block in blocks:
            exec(compile(block, "README.md", "exec"), {})  # the asserts inside are the test


def test_readme_has_badge_disclaimer_and_cli() -> None:
    assert "actions/workflows/ci.yml/badge.svg" in README
    assert "licensed engineer" in README
    for command in ("flood", "fdc", "monthly", "mip", "all"):
        assert f"nepal-hydro {command}" in README


def test_example_prints_the_golden_values(capsys: pytest.CaptureFixture[str]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        runpy.run_path(str(ROOT / "examples" / "solu_khola.py"), run_name="__main__")
    out = capsys.readouterr().out
    for text in ("Q100       426", "Q95       2.03", "Annual mean      16.68     21.12",
                 "Aug              52.45     70.00"):  # fmt: skip
        assert text in out
    assert "warning" not in out


def test_methods_equations_match_the_data() -> None:
    coef = load_wecs_dhm()
    for t in (2, 100):
        f = coef.flood[t]
        assert f"Q_{{{t}}}" in METHODS or f"Q_{t}" in METHODS
        assert f"{f.alpha:.4f}".rstrip("0") in METHODS
        assert f"{f.beta}" in METHODS
    q100 = coef.fdc[100]
    assert isinstance(q100, FdcSquaredSqrt)
    assert f"\\big({q100.c} + {q100.a}\\,\\sqrt{{A_{{5000}} + 1}}" in METHODS


def test_methods_documents_the_caveats() -> None:
    for text in ("Q80 and Q100 are reconstructed", "Region 4 is unconfirmed",
                 "rise with exceedance", "February 29", "ratio_mip_over_wecs",
                 "1 < T ≤ 10 000"):  # fmt: skip
        assert text in METHODS
