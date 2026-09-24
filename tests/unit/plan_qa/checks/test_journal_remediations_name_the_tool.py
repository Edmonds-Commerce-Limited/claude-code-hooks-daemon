"""Every journal remediation names `mkplan.bash --journal` (Plan 00461).

`plan_journal_guard` DENIES a hand-written journal entry. A remediation that
still says "append a `## HH:MM` entry" therefore sends its reader straight
into that deny, so each one must name the stamping tool instead, and none may
prescribe typing a heading or choosing a day-file.
"""

from collections.abc import Callable
from datetime import date

import pytest

from claude_code_hooks_daemon.plan_qa.checks import (
    journal_append_only,
    journal_completion_entry,
    journal_dayfile_is_today,
    journal_entry_future_dated,
    journal_entry_ordering,
    journal_entry_with_progress,
    journal_freshness,
    plan_shrink_without_journal,
)
from claude_code_hooks_daemon.plan_qa.model import journal_append_command
from claude_code_hooks_daemon.plan_qa.remedy import remedy_sentence

PLAN_DIR = "CLAUDE/Plan"
TODAY = date(2026, 9, 24)

REMEDIATIONS: dict[str, Callable[[], str]] = {
    "journal-append-only": lambda: journal_append_only._remediation(PLAN_DIR, 461),
    "journal-entry-with-progress": lambda: journal_entry_with_progress._remediation(PLAN_DIR, 461),
    "journal-completion-entry": lambda: journal_completion_entry._remediation(PLAN_DIR, 461),
    "journal-entry-future-dated": lambda: journal_entry_future_dated._remediation(PLAN_DIR, 461),
    "journal-entry-ordering": lambda: journal_entry_ordering._remediation(PLAN_DIR, 461),
    "journal-freshness": lambda: journal_freshness._remediation(PLAN_DIR),
    "journal-dayfile-is-today": lambda: journal_dayfile_is_today._remediation(PLAN_DIR, 461, TODAY),
    "journal-dayfile-is-today (no plan number)": lambda: journal_dayfile_is_today._remediation(
        PLAN_DIR, None, TODAY
    ),
    "plan-shrink-without-journal": lambda: plan_shrink_without_journal._remediation(
        PLAN_DIR, f"{PLAN_DIR}/00461-x", "JOURNAL", 461
    ),
    "remedy RELOCATE": remedy_sentence,
}


class TestJournalAppendCommand:
    def test_names_the_script_under_the_plan_dir(self) -> None:
        assert journal_append_command(PLAN_DIR, 461, "finding") == (
            'CLAUDE/Plan/mkplan.bash --journal 461 finding <body-file> --title "short title"'
        )

    def test_an_unknown_plan_number_is_a_placeholder(self) -> None:
        assert "--journal <plan-number> <category> " in journal_append_command(PLAN_DIR, None)


@pytest.mark.parametrize("name", sorted(REMEDIATIONS))
def test_names_the_stamping_tool(name: str) -> None:
    assert "mkplan.bash --journal" in REMEDIATIONS[name](), name


@pytest.mark.parametrize("name", sorted(REMEDIATIONS))
def test_never_prescribes_a_hand_typed_heading(name: str) -> None:
    text = REMEDIATIONS[name]()
    assert "## HH:MM" not in text, name
    assert "that day's file" not in text, name
