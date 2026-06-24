"""Tests for BackgroundProcessTrackerHandler (Plan 00142, Layer B).

PostToolUse advisory that fires when a Bash tool call backgrounds a process
(`run_in_background: true` or a `&`/`nohup`/`setsid`/`disown` command). It:
  - records the backgrounded command to a best-effort JSONL state file, and
  - injects rate-limited guidance to run `harvest-background` and manage a
    non-durable watchdog cron — the daemon never kills.
"""

import json

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.background_process_tracker import (
    BackgroundProcessTrackerHandler,
    write_state_record,
)


def _bash(command="echo hi", *, run_in_background=False, session_id="s1"):
    tool_input: dict[str, object] = {"command": command}
    if run_in_background:
        tool_input["run_in_background"] = True
    return {
        "tool_name": "Bash",
        "tool_input": tool_input,
        "session_id": session_id,
    }


class TestInit:
    @pytest.fixture
    def handler(self):
        return BackgroundProcessTrackerHandler()

    def test_name(self, handler):
        assert handler.name == "background-process-tracker"

    def test_priority(self, handler):
        assert handler.priority == 28

    def test_not_terminal(self, handler):
        assert handler.terminal is False

    def test_default_enabled_on(self, handler):
        # User decision: full Layer B, default-ON (rate-limited).
        assert handler.get_default_enabled() is True


class TestMatches:
    @pytest.fixture
    def handler(self):
        return BackgroundProcessTrackerHandler()

    @pytest.mark.parametrize(
        "command,rib",
        [
            ("npm run dev", True),  # run_in_background flag
            ("sleep 1000 &", False),  # trailing single &
            ("nohup ./server.sh", False),
            ("setsid python worker.py", False),
            ("some-daemon & echo started", False),  # mid-command backgrounder
        ],
    )
    def test_matches_backgrounded(self, handler, command, rib):
        assert handler.matches(_bash(command, run_in_background=rib)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "echo hello",
            "ls -la && pwd",  # && is not backgrounding
            "grep x file 2>&1",  # 2>&1 is a redirect, not a backgrounder
            "git commit -m 'x'",
        ],
    )
    def test_does_not_match_foreground(self, handler, command):
        assert handler.matches(_bash(command)) is False

    def test_non_bash_ignored(self, handler):
        assert handler.matches({"tool_name": "Read", "tool_input": {"file_path": "/x"}}) is False


class TestHandleAdvisory:
    @pytest.fixture
    def handler(self, tmp_path, monkeypatch):
        h = BackgroundProcessTrackerHandler()
        # Redirect state writes to a temp file (ProjectContext not initialised in tests).
        monkeypatch.setattr(h, "_resolve_state_file", lambda: tmp_path / "bg.jsonl")
        return h

    def test_first_detection_advises(self, handler):
        result = handler.handle(_bash("sleep 999 &", session_id="sA"))
        assert result.decision == Decision.ALLOW
        text = " ".join(result.context or [])
        assert "harvest-background" in text
        assert "kill -- -" in text
        assert "CronCreate" in text or "watchdog" in text.lower()

    def test_advisory_is_rate_limited_per_session(self, handler):
        first = handler.handle(_bash("a &", session_id="sB"))
        second = handler.handle(_bash("b &", session_id="sB"))
        assert first.context  # advised on first
        assert not second.context  # suppressed on the immediate next

    def test_state_record_written(self, handler, tmp_path):
        handler.handle(_bash("sleep 999 &", session_id="sC"))
        state = tmp_path / "bg.jsonl"
        assert state.exists()
        lines = [ln for ln in state.read_text().splitlines() if ln.strip()]
        record = json.loads(lines[-1])
        assert record["session_id"] == "sC"
        assert "sleep 999" in record["command"]


class TestWriteStateRecord:
    def test_appends_and_bounds_file(self, tmp_path):
        state = tmp_path / "bg.jsonl"
        for i in range(5):
            write_state_record(state, {"command": f"cmd{i} &"}, max_lines=3)
        lines = [ln for ln in state.read_text().splitlines() if ln.strip()]
        # Bounded to the last 3 records.
        assert len(lines) == 3
        commands = [json.loads(ln)["command"] for ln in lines]
        assert commands == ["cmd2 &", "cmd3 &", "cmd4 &"]


class TestMetadata:
    @pytest.fixture
    def handler(self):
        return BackgroundProcessTrackerHandler()

    def test_get_claude_md(self, handler):
        md = handler.get_claude_md()
        assert md is not None
        assert "background_process_tracker" in md
        assert "harvest-background" in md

    def test_get_acceptance_tests(self, handler):
        assert len(handler.get_acceptance_tests()) > 0
