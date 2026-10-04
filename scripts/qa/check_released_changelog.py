#!/usr/bin/env python3
"""Fail when CHANGELOG.md edits a section already released at the latest tag.

A released section is history. Agents looking for "where release notes go" find
the newest section at the top of CHANGELOG.md and append to it, so a note meant
for the next release lands in one that is already published (Plan 00474 N343).
New notes belong in CLAUDE/UPGRADES/UNRELEASED/release-notes/; the release
process writes CHANGELOG.md itself, as a NEW section with no tag yet, which this
check allows.

Every section in the latest ``v*`` tag's CHANGELOG.md is released; the working
tree's text of each must be unchanged from that tag.

Usage:
    python scripts/qa/check_released_changelog.py [--json] [--path DIR]

Exit codes:
    0 - No released section edited
    1 - A released section differs from its tag
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404 - fixed git argv, no shell
import sys
from pathlib import Path
from typing import Any, Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_OUTPUT_FILE: Final[Path] = _PROJECT_ROOT / "untracked" / "qa" / "released_changelog.json"
_CHANGELOG: Final[str] = "CHANGELOG.md"
_NOTES_DIR: Final[str] = "CLAUDE/UPGRADES/UNRELEASED/release-notes/"
_SECTION: Final[re.Pattern[str]] = re.compile(r"^## \[(?P<version>[^\]]+)\]", re.MULTILINE)


def _git(root: Path, *args: str) -> str:
    """Run git in ``root``; any failure raises, so a broken repo never reads as clean."""
    result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout


def parse_sections(text: str) -> dict[str, str]:
    """Map each ``## [version]`` heading to its text, up to the next heading."""
    matches = list(_SECTION.finditer(text))
    ends = [m.start() for m in matches[1:]] + [len(text)]
    return {m.group("version"): text[m.start() : end] for m, end in zip(matches, ends, strict=True)}


def find_violations(root: Path) -> tuple[list[dict[str, Any]], int]:
    """Changed released sections (one record each), and how many sections were checked."""
    tags = _git(root, "tag", "--list", "v*", "--sort=-v:refname").split()
    if not tags:
        return [], 0
    latest = tags[0]
    released = parse_sections(_git(root, "show", f"{latest}:{_CHANGELOG}"))
    current = parse_sections((root / _CHANGELOG).read_text(encoding="utf-8"))
    violations = [
        {
            "file": _CHANGELOG,
            "line": 0,
            "rule": "released-changelog-section-edited",
            "message": (
                f"section [{version}] differs from {latest}; a released section is "
                f"immutable. Put new notes in {_NOTES_DIR}"
            ),
        }
        for version, body in released.items()
        if current.get(version) != body
    ]
    return violations, len(released)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--path", default=str(_PROJECT_ROOT))
    args = parser.parse_args()

    root = Path(args.path).resolve()
    violations, sections_checked = find_violations(root)
    if args.json_output:
        _OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": {
                "passed": not violations,
                "total_violations": len(violations),
                "sections_checked": sections_checked,
            },
            "violations": violations,
        }
        _OUTPUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        for item in violations:
            print(f"{item['file']}  {item['message']}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
