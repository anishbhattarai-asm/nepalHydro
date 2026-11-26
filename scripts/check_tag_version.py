"""Fail unless a release tag (``v`` + a PEP 440 version) matches ``__version__``.

Used by the Release workflow:  python scripts/check_tag_version.py "$GITHUB_REF_NAME"

Versions are compared after PEP 440 normalisation, so pre-releases work and
equivalent spellings match: v0.1.0a1, v0.1.0-alpha.1 and v0.1.0.a1 are all 0.1.0a1.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

INIT = Path(__file__).resolve().parents[1] / "src" / "nepal_hydro" / "__init__.py"


def package_version() -> str:
    for node in ast.parse(INIT.read_text(encoding="utf-8")).body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__version__"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise SystemExit(f"error: no __version__ string in {INIT}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_tag_version.py TAG", file=sys.stderr)
        return 2
    tag = argv[0]
    if not tag.startswith("v"):
        print(f"error: release tags start with 'v', got {tag!r}", file=sys.stderr)
        return 1
    try:
        tagged = Version(tag[1:])
    except InvalidVersion:
        print(f"error: {tag!r} is not v + a PEP 440 version", file=sys.stderr)
        return 1
    declared = Version(package_version())
    if tagged != declared:
        print(f"error: tag {tag} is version {tagged}, but __version__ is {declared}",
              file=sys.stderr)  # fmt: skip
        return 1
    kind = "pre-release" if declared.is_prerelease else "release"
    print(f"ok: tag {tag} matches __version__ {declared} ({kind})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
