"""The journal grammar's categories live in two places; pin them together.

`mkplan.bash` validates `--journal <category>` against a bash array, and
`_JOURNAL_TEMPLATE_.md` states the legal set as prose in its "Entry grammar"
block. The script's own comment says to "keep them in sync by hand", which is
the shape that rots: two copies of one truth, no test.

That is not a hypothetical worry here. Issue #44 was exactly this defect class
in this repository — shipped `plugins:` examples drifted from the model that
had to accept them, undetected, because nothing read the shipped files. The
fix there was a test that reads the real artefacts rather than a copy, and this
is the same fix for the same shape.

Both copies of each file are checked, because the deployed copy under
`CLAUDE/Plan/` and the bundled one under `install/templates/` must agree with
each other as well as with the prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.model import JOURNAL_CATEGORIES

_REPO_ROOT = Path(__file__).resolve().parents[3]

_MKPLAN_COPIES = (
    _REPO_ROOT / "CLAUDE" / "Plan" / "mkplan.bash",
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "mkplan.bash",
)
_TEMPLATE_COPIES = (
    _REPO_ROOT / "CLAUDE" / "Plan" / "_JOURNAL_TEMPLATE_.md",
    _REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "install"
    / "templates"
    / "_JOURNAL_TEMPLATE_.md",
)

#: `readonly JOURNAL_CATEGORIES=(action finding decision ...)`
_BASH_ARRAY = re.compile(r"JOURNAL_CATEGORIES=\(([^)]*)\)")

#: The grammar line: "- `category` ∈ `action` | `finding` | ..."
_PROSE_LINE = re.compile(r"`category`\s*∈\s*(.+)")


def _categories_from_bash(path: Path) -> list[str]:
    match = _BASH_ARRAY.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError(f"no JOURNAL_CATEGORIES array found in {path}")
    return match.group(1).split()


def _categories_from_prose(path: Path) -> list[str]:
    match = _PROSE_LINE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError(f"no `category` ∈ grammar line found in {path}")
    return re.findall(r"`([a-z]+)`", match.group(1))


class TestTheExtractorsActuallyFindSomething:
    """Guard the guard: an extractor that silently matches nothing passes vacuously."""

    @pytest.mark.parametrize("path", _MKPLAN_COPIES, ids=lambda p: p.parent.name)
    def test_the_bash_array_is_found_and_non_empty(self, path: Path) -> None:
        assert len(_categories_from_bash(path)) >= 3

    @pytest.mark.parametrize("path", _TEMPLATE_COPIES, ids=lambda p: p.parent.name)
    def test_the_prose_list_is_found_and_non_empty(self, path: Path) -> None:
        assert len(_categories_from_prose(path)) >= 3


class TestTheTwoTruthsAgree:
    def test_every_mkplan_copy_agrees_with_every_template_copy(self) -> None:
        readings = {str(p): _categories_from_bash(p) for p in _MKPLAN_COPIES}
        readings.update({str(p): _categories_from_prose(p) for p in _TEMPLATE_COPIES})
        # The daemon's own copy, which `plan_journal_guard` prints in its deny
        # reason (Plan 00461). A deny naming a category the tool rejects would
        # send the agent from one refusal straight into another.
        readings["plan_qa.model.JOURNAL_CATEGORIES"] = list(JOURNAL_CATEGORIES)

        distinct = {tuple(v) for v in readings.values()}

        assert len(distinct) == 1, (
            "the journal category set has drifted between the enforcement array "
            f"and the grammar prose: {readings}"
        )

    def test_the_documented_categories_are_the_enforced_ones(self) -> None:
        """Named explicitly, so a silent narrowing of the set is also caught."""
        assert _categories_from_bash(_MKPLAN_COPIES[0]) == [
            "action",
            "finding",
            "decision",
            "thought",
            "blocker",
            "handoff",
            "correction",
        ]
