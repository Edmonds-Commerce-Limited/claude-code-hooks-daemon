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


class TestTheEchoRuleStopsAtTheEndOfItsOwnCommand:
    """`echo\\s+` matched a newline, so the rule reached into the NEXT command.

    Hit live on 2026-09-14 while listing ONE named plan's documents. The command
    was three lines: an `ls`, an `echo` of a separator, and a `wc -l` over
    `CLAUDE/Plan/00403-…/*.md`. Nothing in it can discover a plan number — the
    number is already written in the path — yet it was denied as a discovery
    scan.

    `_COMMAND_SEPARATORS` lists `\\n` precisely so the `echo` rule cannot run
    past its own command, and the comment above the rule says so. The exclusion
    was defeated one character earlier: the `\\s+` between `echo` and its
    arguments matches a newline itself, so the pattern had already crossed into
    the next line before the negated class started. The `;` form was correctly
    left alone throughout, which is what makes this a bug rather than a policy
    — two spellings of the same shell structure got opposite verdicts.
    """

    def test_an_echo_does_not_reach_across_a_newline_into_the_next_command(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """The live reproduction, verbatim."""
        command = (
            "ls CLAUDE/Plan/00403-upstream-issue-reporting-sop/\n"
            'echo "--- wc ---"\n'
            "wc -l CLAUDE/Plan/00403-upstream-issue-reporting-sop/*.md"
        )

        assert handler.matches(_bash(command)) is False

    def test_the_newline_and_the_semicolon_forms_agree(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Same shell structure, two spellings; the verdict must not depend on which.

        The `;` spelling was always correct. Pinning them together means a
        future change cannot fix one and leave the other behind.
        """
        tail = "wc -l CLAUDE/Plan/00403-upstream-issue-reporting-sop/*.md"

        newline_form = handler.matches(_bash(f'echo "--- wc ---"\n{tail}'))
        semicolon_form = handler.matches(_bash(f'echo "--- wc ---"; {tail}'))

        assert newline_form == semicolon_form is False

    def test_a_glob_over_one_named_plans_files_is_not_discovery(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Teeth for the reproduction: the tail alone must be allowed too.

        If this ever denied on its own, the test above would be passing for a
        reason that has nothing to do with the `echo` rule.
        """
        command = "wc -l CLAUDE/Plan/00403-upstream-issue-reporting-sop/*.md"

        assert handler.matches(_bash(command)) is False

    def test_a_genuine_echo_glob_on_the_plan_dir_still_matches(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """The rule keeps its purpose: an `echo` that really does expand the glob."""
        assert handler.matches(_bash("echo CLAUDE/Plan/0*")) is True
        assert handler.matches(_bash("echo CLAUDE/Plan/[0-9]*")) is True

    def test_a_tab_between_echo_and_its_glob_still_matches(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Horizontal whitespace is still whitespace — only the newline is a separator."""
        assert handler.matches(_bash("echo\tCLAUDE/Plan/0*")) is True

    def test_a_line_continuation_still_matches(self, handler: PlanNumberHelperHandler) -> None:
        """`\\<newline>` JOINS two lines into one command, and must not become an escape.

        This is the case that stops the fix from being a bare `[ \\t]+`: a
        backslash-newline is the one newline that is not a separator. The
        handler read the raw command string, so it never saw the normalisation
        `get_bash_command` performs at the daemon's entry point.
        """
        command = "echo \\\nCLAUDE/Plan/0*"

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


class TestAGitCommitMessageIsNotAScan:
    """A commit message DESCRIBING a scan cannot perform one (ledger 00413 N7b).

    Hit live: the commit recording this handler's own niggle entry was denied,
    because the message quoted the command that had just been blocked. A ledger
    entry about a scan must contain the scan it is about, so the handler blocked
    writing down the defect it had itself raised.

    `sed_blocker` already ships exactly this exemption (its exemption 2) and is
    the precedent copied here: sed must follow `git commit` with no command
    separator between the two.
    """

    def test_a_commit_message_quoting_a_plan_glob_is_not_a_discovery_command(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """The reproduction. A `-m` message is text; it lists nothing."""
        command = "git commit -m 'the guard denied ls CLAUDE/Plan/*job* and was right to'"

        assert handler.matches(_bash(command)) is False

    def test_a_commit_message_quoting_a_find_on_the_plan_dir_is_not_a_command(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """Every discovery rule is covered by the exemption, not just the ls one."""
        command = 'git commit -m "do not use find CLAUDE/Plan to get the next number"'

        assert handler.matches(_bash(command)) is False

    def test_staging_then_committing_a_message_about_a_glob_is_still_text(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """A separator BEFORE `git commit` is normal; only one AFTER it matters."""
        command = "git add -A && git commit -m 'ls CLAUDE/Plan/* is blocked deliberately'"

        assert handler.matches(_bash(command)) is False

    def test_a_real_scan_chained_after_a_commit_is_still_denied(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """The exemption must not become a laundering route.

        `git commit -m 'x' && ls CLAUDE/Plan/*` really does run the scan. The
        separator between the commit and the glob is what distinguishes a
        message from a chained command, and it is why the exemption is
        position-sensitive rather than a blanket "contains git commit" test.
        """
        command = "git commit -m 'unrelated' && ls CLAUDE/Plan/*"

        assert handler.matches(_bash(command)) is True

    def test_a_scan_piped_into_a_commit_message_is_still_denied(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """A scan BEFORE the commit is executed regardless of what follows it."""
        command = "ls CLAUDE/Plan/* && git commit -m 'recorded the listing'"

        assert handler.matches(_bash(command)) is True

    def test_a_message_mentioning_the_dir_cannot_launder_a_real_scan_after_it(
        self, handler: PlanNumberHelperHandler
    ) -> None:
        """The hole an exact copy of sed_blocker's exemption would have left.

        sed_blocker anchors on the FIRST occurrence of its trigger word. Copied
        literally, a commit message that mentions the plan directory would
        satisfy the exemption on its first occurrence and carry a genuine scan
        chained after it straight through.

        So this exemption anchors on the LAST occurrence instead: every
        occurrence must sit inside the message for the command to be text.
        """
        command = "git commit -m 'why ls CLAUDE/Plan/* is blocked' && ls CLAUDE/Plan/*"

        assert handler.matches(_bash(command)) is True
