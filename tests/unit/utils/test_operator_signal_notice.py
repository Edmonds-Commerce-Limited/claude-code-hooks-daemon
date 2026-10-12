"""Reading and rendering an operator signal on the daemon side (Plan 00508).

The supervisor types the warning only when a session is idle. The daemon reads
the same file at a tool boundary, so it carries a copy of the supervisor's
validation and fixed wording; the supervisor test pins the two renderers
together.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.operator_signal import (
    KIND_REBOOT_CANCELLED,
    KIND_REBOOT_WARNING,
    KIND_SHUTDOWN_WARNING,
    SIGNAL_TTL_SECONDS,
    read_signal_notice,
    render_operator_message,
    signal_path,
    write_operator_signal,
)

_NOW = 40_000.0
_SESSION = "notice-sess-1"


def _write_raw(untracked: Path, payload: object, session_id: str = _SESSION) -> Path:
    path = signal_path(untracked, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


class TestRenderOperatorMessage:
    def test_reboot_warning_names_minutes(self) -> None:
        text = render_operator_message(KIND_REBOOT_WARNING, 10)
        assert "10 minute(s)" in text
        assert "reboot" in text
        assert text.startswith("🤖 [ccy-supervisor]")

    def test_shutdown_warning_says_no_restore_follows(self) -> None:
        text = render_operator_message(KIND_SHUTDOWN_WARNING, 5)
        assert "5 minute(s)" in text
        assert "NO session restore" in text

    def test_cancelled_carries_no_number(self) -> None:
        text = render_operator_message(KIND_REBOOT_CANCELLED, None)
        assert "cancelled" in text

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown operator signal kind"):
            render_operator_message("bogus", 1)


class TestReadSignalNotice:
    def test_valid_signal_is_returned_with_rendered_text(self, tmp_path: Path) -> None:
        write_operator_signal(
            tmp_path,
            session_id=_SESSION,
            kind=KIND_REBOOT_WARNING,
            minutes=15,
            now=_NOW - 5.0,
        )
        notice, reason = read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert reason is None
        assert notice is not None
        assert notice.ts == _NOW - 5.0
        assert notice.kind == KIND_REBOOT_WARNING
        assert notice.message == render_operator_message(KIND_REBOOT_WARNING, 15)

    def test_cancelled_signal_is_returned(self, tmp_path: Path) -> None:
        write_operator_signal(
            tmp_path,
            session_id=_SESSION,
            kind=KIND_REBOOT_CANCELLED,
            minutes=None,
            now=_NOW - 5.0,
        )
        notice, reason = read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert reason is None
        assert notice is not None
        assert notice.message == render_operator_message(KIND_REBOOT_CANCELLED, None)

    def test_no_file_is_silent(self, tmp_path: Path) -> None:
        assert read_signal_notice(tmp_path, _SESSION, now=_NOW) == (None, None)

    def test_the_file_is_left_in_place(self, tmp_path: Path) -> None:
        path = write_operator_signal(
            tmp_path, session_id=_SESSION, kind=KIND_SHUTDOWN_WARNING, minutes=3, now=_NOW
        )
        before = path.read_bytes()
        read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert path.read_bytes() == before

    def test_expired_signal_is_rejected_with_a_reason(self, tmp_path: Path) -> None:
        write_operator_signal(
            tmp_path,
            session_id=_SESSION,
            kind=KIND_REBOOT_WARNING,
            minutes=10,
            now=_NOW - SIGNAL_TTL_SECONDS - 1.0,
        )
        notice, reason = read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert notice is None
        assert reason is not None
        assert "expired" in reason

    def test_signal_exactly_at_ttl_is_still_live(self, tmp_path: Path) -> None:
        write_operator_signal(
            tmp_path,
            session_id=_SESSION,
            kind=KIND_REBOOT_WARNING,
            minutes=10,
            now=_NOW - SIGNAL_TTL_SECONDS,
        )
        notice, _reason = read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert notice is not None

    def test_other_session_in_file_body_is_rejected(self, tmp_path: Path) -> None:
        _write_raw(
            tmp_path,
            {"ts": _NOW, "session_id": "someone-else", "kind": "reboot-warning", "minutes": 5},
        )
        notice, reason = read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert notice is None
        assert reason is not None
        assert "session" in reason

    @pytest.mark.parametrize(
        "payload",
        [
            "{not json",
            "[1, 2]",
            {"ts": _NOW, "session_id": _SESSION, "kind": "not-a-kind", "minutes": 5},
            {"ts": _NOW, "session_id": _SESSION, "kind": "reboot-warning", "minutes": "5"},
            {"ts": _NOW, "session_id": _SESSION, "kind": "reboot-warning", "minutes": True},
            {"ts": _NOW, "session_id": _SESSION, "kind": "reboot-warning", "minutes": 0},
            {"ts": _NOW, "session_id": _SESSION, "kind": "shutdown-warning"},
        ],
        ids=[
            "bad-json",
            "not-object",
            "unknown-kind",
            "string-minutes",
            "bool-minutes",
            "zero-minutes",
            "missing-minutes",
        ],
    )
    def test_malformed_signal_is_rejected_with_a_reason(
        self, tmp_path: Path, payload: object
    ) -> None:
        _write_raw(tmp_path, payload)
        notice, reason = read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert notice is None
        assert reason

    def test_non_numeric_ts_counts_as_expired(self, tmp_path: Path) -> None:
        _write_raw(
            tmp_path,
            {"ts": "yesterday", "session_id": _SESSION, "kind": "reboot-cancelled"},
        )
        notice, reason = read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert notice is None
        assert reason is not None

    def test_unreadable_path_is_rejected_with_a_reason(self, tmp_path: Path) -> None:
        signal_path(tmp_path, _SESSION).mkdir(parents=True)
        notice, reason = read_signal_notice(tmp_path, _SESSION, now=_NOW)
        assert notice is None
        assert reason
