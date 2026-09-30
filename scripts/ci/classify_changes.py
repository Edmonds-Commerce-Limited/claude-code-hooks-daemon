#!/usr/bin/env python3
"""Classify a change set into the QA tier CI must run (Plan 00475 Phase 3b).

Usage:
    classify_changes.py --base BASE --head HEAD   # diff two refs
    classify_changes.py --paths a.md src/b.py     # classify a given list

Prints one line, ``tier=<docs|code|full>``, ready to append to
``$GITHUB_OUTPUT``. Diagnostics go to stderr.

Tiers:
    full  build or CI config changed, the change set is empty, or the base is
          unknown (all-zero sha on a new ref, empty, or not in history):
          nothing can be narrowed safely
    docs  every path is markdown
    code  anything else

Markdown is narrowed, never skipped: tests read the plan index, ledgers and
docs, so the docs tier still runs the doc and plan checks and the tests the
mapper selects for the changed files (``scripts/qa/run_changed_tests.py``).
All rules live in the table below.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

TIER_DOCS: Final[str] = "docs"
TIER_CODE: Final[str] = "code"
TIER_FULL: Final[str] = "full"

#: THE rule table. A path matching any entry here forces the full tier.
FULL_EXACT_PATHS: Final[frozenset[str]] = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        ".claude/hooks-daemon.yaml",
        "scripts/qa/changed_tests_map.yaml",
    }
)
FULL_PREFIXES: Final[tuple[str, ...]] = (".github/",)
FULL_BASENAMES: Final[frozenset[str]] = frozenset({"conftest.py"})
DOCS_SUFFIX: Final[str] = ".md"

_ZERO_SHA: Final[str] = "0" * 40
_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent


def _is_full(path: str) -> bool:
    return (
        path in FULL_EXACT_PATHS
        or path.startswith(FULL_PREFIXES)
        or path.rsplit("/", 1)[-1] in FULL_BASENAMES
    )


def classify_paths(paths: Sequence[str]) -> str:
    """The tier for a list of changed paths (repo-relative, forward slashes)."""
    if not paths or any(_is_full(path) for path in paths):
        return TIER_FULL
    if all(path.endswith(DOCS_SUFFIX) for path in paths):
        return TIER_DOCS
    return TIER_CODE


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )


def _base_is_known(base: str, root: Path) -> bool:
    if not base or base == _ZERO_SHA:
        return False
    return _git(root, "cat-file", "-e", f"{base}^{{commit}}").returncode == 0


def classify_range(base: str, head: str, root: Path = _PROJECT_ROOT) -> str:
    """The tier for what changed between ``base`` and ``head``.

    An unknown base, or a diff git cannot produce, is ``full``: the safe answer
    when the change set cannot be read is the widest one.
    """
    if not _base_is_known(base, root):
        print(f"base {base!r} is unknown: full tier", file=sys.stderr)
        return TIER_FULL
    # --no-renames lists both sides of a rename, so moving config away counts.
    diff = _git(root, "diff", "--name-only", "--no-renames", base, head)
    if diff.returncode != 0:
        print(f"git diff failed ({diff.stderr.strip()}): full tier", file=sys.stderr)
        return TIER_FULL
    return classify_paths([line for line in diff.stdout.splitlines() if line])


def main(argv: Sequence[str] | None = None) -> int:
    """Print ``tier=<x>``; always exit 0 unless usage is wrong."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--base", help="base ref or sha ('' or all zeros: unknown)")
    source.add_argument("--paths", nargs="+", help="changed paths, instead of a diff")
    parser.add_argument("--head", default="HEAD", help="head ref (default HEAD)")
    args = parser.parse_args(argv)
    if args.paths is not None:
        tier = classify_paths(args.paths)
    else:
        tier = classify_range(args.base, args.head)
    print(f"tier={tier}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
