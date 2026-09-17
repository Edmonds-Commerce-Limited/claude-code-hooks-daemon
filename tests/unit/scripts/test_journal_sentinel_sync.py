"""The UTC sentinel is prose in a template and a constant in a check; pin them.

`_JOURNAL_TEMPLATE_.md` writes one line into every scaffolded day-file saying
the file's timestamps are UTC, and `journal_entry_future_dated` decides which
clock to judge those timestamps by looking for that line. Two copies of one
truth, in two languages, with nothing reading both.

The failure this prevents is SILENT, which is why it needs a test rather than
care. If the template's wording drifts, the check simply stops finding the
sentinel and falls back to the local clock — no error, no failing assertion,
just the Plan 00427 regression quietly restored on every host west of UTC. A
guard whose failure mode is "goes back to being wrong" is exactly the shape
issue #44 taught this repository to pin.

Both template copies are checked: the deployed one under `CLAUDE/Plan/` and the
bundled one under `install/templates/`, which must agree with each other as
well as with the constant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks.journal_entry_future_dated import (
    _UTC_SENTINEL,
    _is_utc_dayfile,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_TEMPLATE_COPIES = (
    _REPO_ROOT / "CLAUDE" / "Plan" / "_JOURNAL_TEMPLATE_.md",
    _REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "install"
    / "templates"
    / "_JOURNAL_TEMPLATE_.md",
)


def _sentinel_line(path: Path) -> str:
    """The template's own sentinel line, found by its stable prefix."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("_Scaffolded by"):
            return line
    raise AssertionError(f"no `_Scaffolded by ...` sentinel line found in {path}")


class TestTheExtractorActuallyFindsSomething:
    """Guard the guard: a finder that matches nothing would pass vacuously."""

    @pytest.mark.parametrize("path", _TEMPLATE_COPIES, ids=lambda p: p.parent.name)
    def test_a_sentinel_line_exists(self, path: Path) -> None:
        assert len(_sentinel_line(path)) > len("_Scaffolded by")


class TestTheCheckRecognisesWhatTheTemplateWrites:
    @pytest.mark.parametrize("path", _TEMPLATE_COPIES, ids=lambda p: p.parent.name)
    def test_the_constant_is_a_substring_of_the_shipped_line(self, path: Path) -> None:
        assert _UTC_SENTINEL in _sentinel_line(path)

    @pytest.mark.parametrize("path", _TEMPLATE_COPIES, ids=lambda p: p.parent.name)
    def test_the_whole_template_is_recognised_as_a_utc_dayfile(self, path: Path) -> None:
        """The real file, not a reconstruction of it — the #44 lesson."""
        assert _is_utc_dayfile(path.read_text(encoding="utf-8"))

    def test_both_copies_carry_the_identical_sentinel_line(self) -> None:
        lines = {str(p): _sentinel_line(p) for p in _TEMPLATE_COPIES}
        assert len(set(lines.values())) == 1, lines


class TestALegacyDayfileIsNotMistakenForOne:
    def test_a_preamble_without_the_sentinel_is_not_a_utc_dayfile(self) -> None:
        """Absence of the sentinel is what marks the 2207 legacy entries."""
        assert not _is_utc_dayfile("# Plan 00377 — Journal 26-09-11\n\n## 09:15 · action · —\n")
