"""The write-clobber guard judged the way the daemon dispatches it (Plan 00422 N29).

The chain calls ``handle()`` only when ``matches()`` returned True. The guard
recorded a successful ``Write`` inside ``handle()``, but ``matches()`` returned
False for exactly the Writes that should be recorded (a new file, or a file
already known), so the recording line never ran in production. A session that
CREATED a file with ``Write`` was then denied ``R-WRITE-CLOBBER`` when it
rewrote that file, against the deny text's own promise that "a file you wrote
or read earlier in this session is not blocked either".

The pre-existing test for this promise called ``handle()`` directly, skipping
the gate the chain applies, so it passed while the product was broken. Every
test here goes through :func:`_dispatch`, which applies that gate.
"""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.write_clobber_guard import (
    WriteClobberGuardHandler,
)

_SESSION = "session-n29"
_OTHER_SESSION = "session-other"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> WriteClobberGuardHandler:
    return WriteClobberGuardHandler()


def _payload(tool_name: str, path: str, session: str = _SESSION) -> dict[str, Any]:
    tool_input: dict[str, Any] = {"file_path": path}
    if tool_name == "Write":
        tool_input["content"] = "replacement\n"
    if tool_name == "Edit":
        tool_input["old_string"] = "a"
        tool_input["new_string"] = "b"
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def _dispatch(handler: WriteClobberGuardHandler, hook_input: dict[str, Any]) -> Decision:
    """What the chain does: ``handle()`` runs only behind a True ``matches()``."""
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestAWriteCreatedFileIsKnown:
    def test_rewriting_a_file_this_session_created_is_allowed(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        """The field report: create with Write, then replace with Write."""
        target = tmp_path / "gate.sh"
        assert _dispatch(handler, _payload("Write", str(target))) == Decision.ALLOW
        target.write_text("#!/bin/sh\necho first\n")

        assert _dispatch(handler, _payload("Write", str(target))) == Decision.ALLOW

    def test_another_sessions_create_does_not_count(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        """Knowledge is per session: a different session never saw the content."""
        target = tmp_path / "gate.sh"
        assert _dispatch(handler, _payload("Write", str(target), _OTHER_SESSION)) == Decision.ALLOW
        target.write_text("written by the other session\n")

        assert _dispatch(handler, _payload("Write", str(target))) == Decision.DENY

    def test_a_denied_clobber_is_not_recorded_as_knowledge(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        """A Write the guard refused never ran, so it taught nothing."""
        target = tmp_path / "existing.txt"
        target.write_text("ORIGINAL\n")
        assert _dispatch(handler, _payload("Write", str(target))) == Decision.DENY

        assert _dispatch(handler, _payload("Write", str(target))) == Decision.DENY


class TestAnEditTouchedFileIsKnown:
    def test_writing_a_file_this_session_edited_is_allowed(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "edited.txt"
        target.write_text("a\n")
        assert _dispatch(handler, _payload("Edit", str(target))) == Decision.ALLOW

        assert _dispatch(handler, _payload("Write", str(target))) == Decision.ALLOW

    def test_another_sessions_edit_does_not_count(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "edited.txt"
        target.write_text("a\n")
        assert _dispatch(handler, _payload("Edit", str(target), _OTHER_SESSION)) == Decision.ALLOW

        assert _dispatch(handler, _payload("Write", str(target))) == Decision.DENY


class TestReadStillWorksThroughDispatch:
    def test_a_read_file_can_be_rewritten(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "read.txt"
        target.write_text("content\n")
        assert _dispatch(handler, _payload("Read", str(target))) == Decision.ALLOW

        assert _dispatch(handler, _payload("Write", str(target))) == Decision.ALLOW

    def test_an_unread_existing_file_is_still_denied(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "untouched.txt"
        target.write_text("content\n")

        assert _dispatch(handler, _payload("Write", str(target))) == Decision.DENY


class TestSpellingsOfOnePathAreOnePath:
    def test_a_dot_dot_spelling_of_a_read_path_is_known(
        self, handler: WriteClobberGuardHandler, tmp_path: Path
    ) -> None:
        """Two spellings of one absolute path name one file."""
        (tmp_path / "sub").mkdir()
        target = tmp_path / "read.txt"
        target.write_text("content\n")
        dotted = str(tmp_path / "sub" / ".." / "read.txt")
        assert _dispatch(handler, _payload("Read", dotted)) == Decision.ALLOW

        assert _dispatch(handler, _payload("Write", str(target))) == Decision.ALLOW
