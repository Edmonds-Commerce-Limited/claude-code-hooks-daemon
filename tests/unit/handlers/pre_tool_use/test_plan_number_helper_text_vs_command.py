"""plan_number_helper must match COMMANDS, not text that mentions them (Plan 00227).

Every rule in this handler matches the raw command string, with no model of
shell structure. So a command that merely NAMES the plan directory near the
handler's trigger vocabulary is treated as the plan-number discovery idiom.

All four scenarios below were hit live during ordinary plan housekeeping on
2026-08-13. The prose case is the sharpest: it touches no filesystem, lists
nothing, and cannot discover any plan number.

Plan 00138 audited this handler and explicitly cleared the sort+truncate rule as
"already narrow", reasoning correctly about which COMMAND SHAPES satisfy it and
never asking whether non-command TEXT could. These tests encode that missing
question so the answer cannot regress to an opinion again.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from claude_code_hooks_daemon.constants import HookInputField, ToolName
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper import (
    PlanNumberHelperHandler,
)

_PLAN_DIR = "CLAUDE/Plan"


@pytest.fixture(autouse=True)
def mock_project_context() -> Iterator[None]:
    """Mock ProjectContext so the handler can be instantiated."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield


@pytest.fixture
def handler(tmp_path: Path) -> PlanNumberHelperHandler:
    """Handler with planning mode enabled."""
    instance = PlanNumberHelperHandler()
    instance._workspace_root = tmp_path
    instance._track_plans_in_project = _PLAN_DIR
    return instance


def _bash(command: str) -> dict[str, object]:
    return {
        HookInputField.TOOL_NAME: ToolName.BASH,
        HookInputField.TOOL_INPUT: {"command": command},
    }


class TestTextThatOnlyMentionsThePlanDirectory:
    """Text is not a command. Naming the vocabulary must not trigger a denial."""

    def test_prose_naming_the_trigger_words_is_not_a_discovery_command(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Reproduced live: an echo of an English sentence was blocked.

        This is the case that proves the rule is not merely mistuned. There is
        no filesystem access here at all.
        """
        command = (
            'echo "harmless text mentioning CLAUDE/Plan and the words ' 'sort and tail -1 together"'
        )

        assert handler.matches(_bash(command)) is False

    def test_reading_the_newest_journal_dayfile_of_a_named_plan_is_allowed(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Finding a NAMED plan's newest journal file is not number discovery.

        This is the operation the plan-workflow guidance actively recommends,
        and it legitimately needs sort + a tail-style reduction.
        """
        command = "git ls-files CLAUDE/Plan/00163-plan-journalling/JOURNAL | sort | tail -1"

        assert handler.matches(_bash(command)) is False

    def test_a_quoted_grep_regex_class_is_not_a_shell_glob(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """`[0-9]` inside single quotes is a regex, not a glob metacharacter."""
        command = "echo \"count: $(grep -cE '^CLAUDE/Plan/[0-9]' folders.txt)\""

        assert handler.matches(_bash(command)) is False

    def test_an_alternation_naming_both_archives_counts_as_covering_them(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """The carve-out must recognise archive coverage expressed as a regex.

        Asserted against `_covers_archive_subdirectories` DIRECTLY, not through
        `matches()`. Routed through `matches()` this case passes vacuously — no
        rule fires on the command at all, so it would go green while the
        carve-out stayed blind. A test that cannot fail proves nothing.

        The gap is real but LATENT rather than live: the carve-out only applies
        when the command is not also extracting a single highest value, and the
        sort+truncate rule's trigger is near-identical to that condition, so no
        currently-reachable denial depends on it. Guarded here so a future rule
        cannot make it live unnoticed.
        """
        command = (
            "git ls-files CLAUDE/Plan | grep -oE "
            "'^CLAUDE/Plan/(Completed/|Cancelled/)?[0-9]+[^/]*/'"
        )

        assert handler._covers_archive_subdirectories(command, _PLAN_DIR) is True

    def test_the_archive_coverage_guard_is_not_vacuous(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Teeth: a command that does NOT reach the archives must not qualify."""
        command = "ls -d CLAUDE/Plan/0*"

        assert handler._covers_archive_subdirectories(command, _PLAN_DIR) is False


class TestGenuineDiscoveryIsStillBlocked:
    """The handler's purpose is intact. Silence here would be the worse failure."""

    def test_the_canonical_discovery_idiom_still_matches(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Sorting a plan-dir listing and taking the last entry IS discovery."""
        command = "ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1"

        assert handler.matches(_bash(command)) is True

    def test_a_bare_find_on_the_plan_dir_still_matches(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        command = "find CLAUDE/Plan -maxdepth 1 -type d"

        assert handler.matches(_bash(command)) is True

    def test_an_ls_glob_on_the_plan_dir_still_matches(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        command = "ls CLAUDE/Plan/[0-9]*"

        assert handler.matches(_bash(command)) is True

    def test_discovery_is_blocked_even_when_a_quoted_string_appears_elsewhere(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """A quoted span must not become a way to smuggle discovery past the rule.

        This is the inverse of the exemption: blanking quoted spans is only safe
        if the UNQUOTED remainder is still scanned.
        """
        command = "echo 'just a note' && ls -d CLAUDE/Plan/0* | sort -V | tail -1"

        assert handler.matches(_bash(command)) is True


class TestHandlerSelfDescriptionMatchesBehaviour:
    """The module docstring claimed the opposite of what the handler does."""

    def test_the_handler_is_terminal_and_therefore_can_block(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Guard the fact the docstring got wrong.

        A reader who believes this handler cannot deny will mis-diagnose every
        block it issues.
        """
        assert handler.terminal is True

    def test_the_module_docstring_does_not_claim_to_be_non_blocking(self) -> None:
        """The docstring must not tell a reader this handler never denies."""
        import claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper as module

        docstring = (module.__doc__ or "").lower()

        assert "non-blocking" not in docstring
        assert "doesn't prevent execution" not in docstring
