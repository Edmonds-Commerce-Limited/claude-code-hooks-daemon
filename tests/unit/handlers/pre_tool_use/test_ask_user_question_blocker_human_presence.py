"""AskUserQuestionBlockerHandler: recent human presence overrides unattended (N274).

The owner typed a real message and the very next AskUserQuestion was denied as
"no human is reading this session". A genuine human prompt inside the recency
window is proof a human is present, so the question is allowed even when the
project declares the unattended mode.
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.ask_user_question_blocker import (
    AskUserQuestionBlockerHandler,
)

SESSION = "session-a"


@pytest.fixture(autouse=True)
def _reset_data_layer() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _stamp(seconds_ago: float) -> str:
    return (
        datetime.fromtimestamp(time.time() - seconds_ago, tz=UTC).isoformat().replace("+00:00", "Z")
    )


def _user(
    content: str, seconds_ago: float, *, session: str = SESSION, origin: str = "human"
) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": content},
            "timestamp": _stamp(seconds_ago),
            "sessionId": session,
            "origin": {"kind": origin},
        }
    )


def _transcript(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _ask(transcript: Path | None, session: str | None = SESSION) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Which one?", "options": []}]},
    }
    if transcript is not None:
        payload["transcript_path"] = str(transcript)
    if session is not None:
        payload["session_id"] = session
    return payload


def _handler(mode: str, minutes: float | None = None) -> AskUserQuestionBlockerHandler:
    class _Handler(AskUserQuestionBlockerHandler):
        """Declares the options the registry sets by setattr, like the other doubles."""

        def __init__(self) -> None:
            super().__init__()
            self._mode = mode
            if minutes is not None:
                self._human_presence_minutes = minutes

    return _Handler()


class TestUnattendedWithHumanPresence:
    def test_recent_human_prompt_allows_the_question(self, tmp_path: Path) -> None:
        path = _transcript(tmp_path, _user("human here - take me through decisions", 30))
        result = _handler("unattended").handle(_ask(path))
        assert result.decision == Decision.ALLOW

    def test_old_human_prompt_still_denies(self, tmp_path: Path) -> None:
        path = _transcript(tmp_path, _user("hello", 31 * 60))
        result = _handler("unattended").handle(_ask(path))
        assert result.decision == Decision.DENY

    def test_deny_reason_names_what_was_judged(self, tmp_path: Path) -> None:
        path = _transcript(tmp_path, _user("hello", 31 * 60))
        result = _handler("unattended").handle(_ask(path))
        assert "no genuine human prompt in this session in the last 30 minutes" in (
            result.reason or ""
        )

    @pytest.mark.parametrize(
        "content",
        [
            "[tick:failsafe]\n**FAILSAFE RECOVERY CHECK** go",
            "[tick:job:issue-sdlc]\nISSUE SDLC TICK",
            "\U0001f916 [ccy-supervisor 2026-09-30 11:59:00] continue",
            '<teammate-message teammate_id="x">hi</teammate-message>',
            "<task-notification>done</task-notification>",
        ],
    )
    def test_recent_automated_prompt_does_not_count(self, tmp_path: Path, content: str) -> None:
        path = _transcript(tmp_path, _user(content, 5))
        result = _handler("unattended").handle(_ask(path))
        assert result.decision == Decision.DENY

    def test_recent_peer_message_does_not_count(self, tmp_path: Path) -> None:
        path = _transcript(tmp_path, _user("a plain sentence", 5, origin="peer"))
        result = _handler("unattended").handle(_ask(path))
        assert result.decision == Decision.DENY

    def test_other_sessions_prompt_does_not_count(self, tmp_path: Path) -> None:
        path = _transcript(tmp_path, _user("hello", 5, session="session-b"))
        result = _handler("unattended").handle(_ask(path))
        assert result.decision == Decision.DENY

    def test_no_transcript_path_denies(self) -> None:
        result = _handler("unattended").handle(_ask(None))
        assert result.decision == Decision.DENY

    def test_missing_transcript_file_denies(self, tmp_path: Path) -> None:
        result = _handler("unattended").handle(_ask(tmp_path / "absent.jsonl"))
        assert result.decision == Decision.DENY

    def test_window_is_configurable(self, tmp_path: Path) -> None:
        path = _transcript(tmp_path, _user("hello", 10 * 60))
        assert _handler("unattended", 5.0).handle(_ask(path)).decision == Decision.DENY
        assert _handler("unattended", 15.0).handle(_ask(path)).decision == Decision.ALLOW

    def test_zero_window_disables_the_override(self, tmp_path: Path) -> None:
        path = _transcript(tmp_path, _user("hello", 1))
        assert _handler("unattended", 0.0).handle(_ask(path)).decision == Decision.DENY


class TestOtherModesUnchanged:
    def test_strict_mode_still_requires_the_prefix_with_human_present(self, tmp_path: Path) -> None:
        path = _transcript(tmp_path, _user("hello", 5))
        result = _handler("strict").handle(_ask(path))
        assert result.decision == Decision.DENY
