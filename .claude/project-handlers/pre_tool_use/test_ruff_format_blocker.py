"""Tests for RuffFormatBlockerHandler — Plan 00419 niggle N7 (RED first).

The niggle: **Black is this project's formatter of record; Ruff is its
linter.** `CLAUDE/QA.md:48` says so plainly, and running `ruff format` anyway
is what put 163 files into a commit meant to carry 8 (`344ebf16`), 82 of which
the next QA run rewrote back to Black's style.

The reason it is a niggle rather than one person's slip: both formatters are
installed, both are a natural reach, and `ruff format` **succeeds**. It reports
confidently and leaves a tree that passes `ruff format --check`. Nothing
objects until a later QA run rewrites the files, by which point the churn is in
pushed history and mixed into an unrelated diff — so the cost lands on whoever
reads that diff, not on whoever caused it.

This repository's whole argument is that a rule stated in prose and enforced by
nothing gets broken. N7 is that argument tested on its own author, hours after
reading the prose.
"""

from typing import Any

import pytest
from ruff_format_blocker import RuffFormatBlockerHandler

from claude_code_hooks_daemon.core.hook_result import Decision


class TestIdentity:
    @pytest.fixture
    def handler(self) -> RuffFormatBlockerHandler:
        return RuffFormatBlockerHandler()

    def test_name(self, handler: RuffFormatBlockerHandler) -> None:
        assert handler.name == "ruff-format-blocker"

    def test_terminal(self, handler: RuffFormatBlockerHandler) -> None:
        assert handler.terminal is True

    def test_tags(self, handler: RuffFormatBlockerHandler) -> None:
        assert "project" in handler.tags
        assert "blocking" in handler.tags


class TestItBlocksTheWrongFormatter:
    """Every spelling that actually reformats the tree."""

    @pytest.fixture
    def handler(self) -> RuffFormatBlockerHandler:
        return RuffFormatBlockerHandler()

    def test_the_originating_command(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """Verbatim from niggle N7 — the command that cost 163 files."""
        command = "python -m ruff format src/claude_code_hooks_daemon tests/unit"

        assert handler.matches(bash_hook_input(command)) is True

    def test_a_bare_ruff_format(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("ruff format .")) is True

    def test_a_venv_absolute_path(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """The venv is resolved by a script here, so the path form is the common one."""
        command = "/workspace/untracked/venv-x/bin/python -m ruff format src"

        assert handler.matches(bash_hook_input(command)) is True

    def test_a_later_segment_of_a_compound_command(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """A harmless leading segment must not buy cover for the rest."""
        command = "git status && ruff format src"

        assert handler.matches(bash_hook_input(command)) is True

    def test_the_check_variant_is_also_blocked(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """`--check` writes nothing, and is still the trap.

        It answers confidently about a tree Black owns, so a green
        `ruff format --check` is a FALSE reassurance — which is the half of N7
        that made the mistake survive as long as it did.
        """
        assert handler.matches(bash_hook_input("ruff format --check src")) is True


class TestItLeavesTheRightToolsAlone:
    """The false positives that would get this switched off."""

    @pytest.fixture
    def handler(self) -> RuffFormatBlockerHandler:
        return RuffFormatBlockerHandler()

    def test_ruff_check_is_the_linter_and_is_allowed(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """Ruff IS this project's linter. Only its formatter is wrong here."""
        assert handler.matches(bash_hook_input("ruff check src")) is False

    def test_ruff_check_with_fix_is_allowed(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """`--fix` applies LINT fixes, which is the linter doing its job."""
        assert handler.matches(bash_hook_input("ruff check --fix src")) is False

    def test_black_is_allowed(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("python -m black src")) is False

    def test_the_autofix_script_is_allowed(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """The command the deny message recommends must not itself be denied."""
        assert handler.matches(bash_hook_input("./scripts/qa/run_autofix.sh")) is False

    def test_grepping_for_the_phrase_is_allowed(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """Searching for a mistake is the work of cleaning it up."""
        command = "grep -rn 'ruff format' scripts/"

        assert handler.matches(bash_hook_input(command)) is False

    def test_a_commit_message_mentioning_it_is_allowed(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """N7's own write-up has to be committable.

        The sibling `enforce_llm_qa` handler learned this by hitting it while
        writing the very commit that described the guarded script.
        """
        command = "git commit -m 'Record N7: ruff format is not the formatter here'"

        assert handler.matches(bash_hook_input(command)) is False

    def test_reading_a_file_that_mentions_it_is_allowed(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("cat scripts/qa/run_autofix.sh")) is False

    def test_a_non_bash_tool_is_ignored(
        self, handler: RuffFormatBlockerHandler, write_hook_input: Any
    ) -> None:
        """This judges a COMMAND. A document may say `ruff format` freely."""
        assert handler.matches(write_hook_input("/tmp/notes.md", "run ruff format")) is False


class TestTheDenial:
    """A deny that does not name the right tool just costs a turn."""

    @pytest.fixture
    def handler(self) -> RuffFormatBlockerHandler:
        return RuffFormatBlockerHandler()

    def test_it_denies(self, handler: RuffFormatBlockerHandler, bash_hook_input: Any) -> None:
        result = handler.handle(bash_hook_input("ruff format src"))

        assert result.decision is Decision.DENY

    def test_it_names_the_formatter_of_record(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        result = handler.handle(bash_hook_input("ruff format src"))

        # `reason` is `str | None`; asserting it is present first is what makes
        # the membership checks below type-safe, and it is a real assertion in
        # its own right — a deny with no reason at all would be a worse defect
        # than one whose wording drifted.
        assert result.reason is not None
        assert "Black" in result.reason

    def test_it_names_the_command_to_run_instead(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """The failure mode is 'right family, wrong entry point'.

        So the remedy has to be the entry point, not just a prohibition.
        """
        result = handler.handle(bash_hook_input("ruff format src"))

        assert result.reason is not None
        assert "run_autofix.sh" in result.reason

    def test_it_says_ruff_is_still_the_linter(
        self, handler: RuffFormatBlockerHandler, bash_hook_input: Any
    ) -> None:
        """Otherwise the lesson taken away is 'ruff is banned', which is wrong."""
        result = handler.handle(bash_hook_input("ruff format src"))

        assert result.reason is not None
        assert "ruff check" in result.reason
