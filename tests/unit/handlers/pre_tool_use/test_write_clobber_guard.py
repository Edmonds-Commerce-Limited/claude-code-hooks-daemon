"""Tests for the write-clobber guard (Plan 00261).

`Write` replaces a file's entire contents. When the target exists and the agent
has not read it, everything in it is destroyed with no warning and no diff --
the agent cannot even report what was lost, because it never knew.

This happened in this repository: a `Write` destroyed a tracked 58-line journal
a sub-agent had committed minutes earlier, and it was caught only because that
path happened to be covered by an ADVISE-level plan-QA rule.

The guard tracks READS rather than sizes, and Decision 1 of the plan records
why: the clobbering write GREW the file (58 -> ~67 lines), so every
shrink-threshold design would have passed it. The destructive property was
replacement without knowledge, not shrinkage.
"""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.write_clobber_guard import (
    WriteClobberGuardHandler,
)

_SESSION = "session-abc"


def _read(path: str, session: str = _SESSION) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session,
        "tool_name": "Read",
        "tool_input": {"file_path": path},
    }


def _write(path: str, session: str = _SESSION) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session,
        "tool_name": "Write",
        "tool_input": {"file_path": path, "content": "replacement"},
    }


@pytest.fixture
def handler() -> WriteClobberGuardHandler:
    return WriteClobberGuardHandler()


@pytest.fixture
def existing_file(tmp_path: Path) -> str:
    target = tmp_path / "existing.txt"
    target.write_text("ORIGINAL CONTENT\nline2\nline3\n")
    return str(target)


class TestInitialization:
    def test_handler_id(self, handler: WriteClobberGuardHandler) -> None:
        assert handler.handler_id == HandlerID.WRITE_CLOBBER_GUARD

    def test_priority_is_in_the_safety_band(self, handler: WriteClobberGuardHandler) -> None:
        assert handler.priority == Priority.WRITE_CLOBBER_GUARD

    def test_handler_is_not_terminal(self, handler: WriteClobberGuardHandler) -> None:
        """Terminal ALLOW would shadow every handler behind it (Plan 00241).

        This handler ALLOWs on the common path (recording a read), so making it
        terminal would silently disable the rest of the chain. The daemon merges
        decisions most-restrictive-wins, so a non-terminal DENY still denies.
        """
        assert handler.terminal is False


class TestMatches:
    def test_matches_write_to_existing_unread_file(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        assert handler.matches(_write(existing_file)) is True

    def test_does_not_match_write_to_new_path(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        """Creating a new file is the common case and must stay frictionless."""
        assert handler.matches(_write(str(tmp_path / "brand-new.txt"))) is False

    def test_matches_read_so_it_can_record(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        """The handler must see Reads to record them; it never denies one."""
        assert handler.matches(_read(existing_file)) is True

    def test_does_not_match_edit(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        """Edit is not a clobber - it is a targeted replacement of known text."""
        hook_input = _write(existing_file)
        hook_input["tool_name"] = "Edit"
        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_file_path(self, handler: WriteClobberGuardHandler) -> None:
        assert handler.matches({"tool_name": "Write", "tool_input": {}}) is False


class TestReadClearsTheBlock:
    def test_write_allowed_after_reading_that_path(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        handler.handle(_read(existing_file))
        assert handler.matches(_write(existing_file)) is False

    def test_reading_a_different_path_does_not_clear_it(
        self, handler: WriteClobberGuardHandler, existing_file: str, tmp_path: Path
    ) -> None:
        other = tmp_path / "other.txt"
        other.write_text("unrelated")
        handler.handle(_read(str(other)))
        assert handler.matches(_write(existing_file)) is True

    def test_read_in_another_session_does_not_clear_it(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        """State is per session -- one session's read is not another's knowledge."""
        handler.handle(_read(existing_file, session="other-session"))
        assert handler.matches(_write(existing_file)) is True

    def test_allowed_write_records_the_path(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        """After writing a file yourself, you know its contents.

        Without this, creating a file and then rewriting it in the same session
        would be blocked on the second write, which would be absurd.
        """
        new_path = tmp_path / "created.txt"
        handler.handle(_write(str(new_path)))
        new_path.write_text("now it exists")
        assert handler.matches(_write(str(new_path))) is False


class TestHandle:
    def test_denies_clobbering_write(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        result = handler.handle(_write(existing_file))
        assert result.decision == Decision.DENY

    def test_reason_names_the_remedy(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        result = handler.handle(_write(existing_file))
        assert result.reason is not None
        assert "Read" in result.reason
        assert "Edit" in result.reason

    def test_reason_reports_what_would_be_lost(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        """The agent cannot report what it never knew - so the guard reports it."""
        result = handler.handle(_write(existing_file))
        assert result.reason is not None
        assert "3" in result.reason, "should state the line count at risk"

    def test_read_is_allowed_and_never_denied(
        self, handler: WriteClobberGuardHandler, existing_file: str
    ) -> None:
        result = handler.handle(_read(existing_file))
        assert result.decision == Decision.ALLOW


class TestGuidanceAndAcceptanceTests:
    def test_get_claude_md_present(self, handler: WriteClobberGuardHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "write_clobber_guard" in guidance

    def test_acceptance_tests_have_deny_and_allow(self, handler: WriteClobberGuardHandler) -> None:
        decisions = {t.expected_decision for t in handler.get_acceptance_tests()}
        assert Decision.DENY in decisions
        assert Decision.ALLOW in decisions
