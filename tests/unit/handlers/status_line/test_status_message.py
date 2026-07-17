"""Tests for StatusMessageHandler.

Renders a transient supervisor message from the shared message file
(``supervise/status-message.json``) written by the ccy PTY supervisor's
``StatusMessagePoster``. The Ctrl+Z "ignored" notice is its first consumer.

Fail-silent by design (mirrors ``supervisor_indicator``): an absent, expired,
malformed, or unexpectedly-unreadable file renders NO segment and never raises,
so the handler is safe to ship on by default — a project that never runs the
supervisor simply shows nothing.
"""

import json
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.handlers.status_line.status_message import (
    StatusMessageHandler,
)

_PATH_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.status_message."
    "StatusMessageHandler._message_file_path"
)
_NOW_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.status_message." "StatusMessageHandler._now"
)
_READ_PATCH = (
    "claude_code_hooks_daemon.handlers.status_line.status_message."
    "StatusMessageHandler._read_message"
)


def _write(tmp_path: Path, text: str, expires_at: float) -> Path:
    path = tmp_path / "status-message.json"
    path.write_text(json.dumps({"text": text, "expires_at": expires_at}))
    return path


class TestStatusMessageInit:
    def test_identity_and_flags(self) -> None:
        handler = StatusMessageHandler()
        assert handler.handler_id == HandlerID.STATUS_MESSAGE
        assert handler.priority == Priority.STATUS_MESSAGE
        assert handler.terminal is False
        assert HandlerTag.STATUSLINE in handler.tags
        assert HandlerTag.NON_TERMINAL in handler.tags

    def test_default_enabled(self) -> None:
        assert StatusMessageHandler().get_default_enabled() is True

    def test_matches_always_true(self) -> None:
        assert StatusMessageHandler().matches({}) is True

    def test_get_claude_md_is_none(self) -> None:
        assert StatusMessageHandler().get_claude_md() is None

    def test_get_acceptance_tests_nonempty(self) -> None:
        assert len(StatusMessageHandler().get_acceptance_tests()) >= 1


class TestStatusMessageRender:
    def test_present_and_unexpired_renders_text(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "Ctrl+Z ignored", expires_at=100.0)
        handler = StatusMessageHandler()
        with patch(_PATH_PATCH, return_value=path), patch(_NOW_PATCH, return_value=95.0):
            result = handler.handle({})
        assert len(result.context) == 1
        assert "Ctrl+Z ignored" in result.context[0]

    def test_absent_file_renders_nothing(self, tmp_path: Path) -> None:
        missing = tmp_path / "status-message.json"
        handler = StatusMessageHandler()
        with patch(_PATH_PATCH, return_value=missing), patch(_NOW_PATCH, return_value=1.0):
            assert handler.handle({}).context == []

    def test_expired_renders_nothing(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "stale", expires_at=100.0)
        handler = StatusMessageHandler()
        with patch(_PATH_PATCH, return_value=path), patch(_NOW_PATCH, return_value=100.0):
            # now == expires_at is already expired (strict less-than window).
            assert handler.handle({}).context == []
        with patch(_PATH_PATCH, return_value=path), patch(_NOW_PATCH, return_value=250.0):
            assert handler.handle({}).context == []

    def test_malformed_json_renders_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "status-message.json"
        path.write_text("{not valid json")
        handler = StatusMessageHandler()
        with patch(_PATH_PATCH, return_value=path), patch(_NOW_PATCH, return_value=1.0):
            assert handler.handle({}).context == []

    def test_non_dict_json_renders_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "status-message.json"
        path.write_text("[1, 2, 3]")
        handler = StatusMessageHandler()
        with patch(_PATH_PATCH, return_value=path), patch(_NOW_PATCH, return_value=1.0):
            assert handler.handle({}).context == []

    def test_empty_text_renders_nothing(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "   ", expires_at=100.0)
        handler = StatusMessageHandler()
        with patch(_PATH_PATCH, return_value=path), patch(_NOW_PATCH, return_value=1.0):
            assert handler.handle({}).context == []

    def test_missing_expires_at_renders_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "status-message.json"
        path.write_text('{"text": "no ttl"}')
        handler = StatusMessageHandler()
        with patch(_PATH_PATCH, return_value=path), patch(_NOW_PATCH, return_value=1.0):
            assert handler.handle({}).context == []

    def test_non_numeric_expires_at_renders_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "status-message.json"
        path.write_text('{"text": "bad ttl", "expires_at": "soon"}')
        handler = StatusMessageHandler()
        with patch(_PATH_PATCH, return_value=path), patch(_NOW_PATCH, return_value=1.0):
            assert handler.handle({}).context == []

    def test_unexpected_error_fails_silent(self, tmp_path: Path) -> None:
        handler = StatusMessageHandler()
        with patch(_READ_PATCH, side_effect=RuntimeError("boom")):
            # Any unexpected failure must render nothing, never propagate.
            assert handler.handle({}).context == []
