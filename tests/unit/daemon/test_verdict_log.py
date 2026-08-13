"""Tests for the verdict log writer (Plan 00209).

The verdict log is the daemon's persistent record of "which handler fired,
on which tool call, with what verdict" — the missing capability the field
report in CLAUDE/Plan/00209-field-feedback-daemon-self-observability/FEEDBACK.md
calls the highest-value gap. These tests cover the pure, dependency-free
helpers; the daemon controller wiring is covered separately.
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.core.chain import HandlerVerdict
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.daemon.verdict_log import (
    VERDICT_LOG_FILENAME,
    append_verdicts,
    build_verdict_lines,
    escape_hatch_used,
)


class TestEscapeHatchUsed:
    """escape_hatch_used detects the shared MUST_..._BECAUSE= convention."""

    def test_true_when_marker_in_bash_command(self) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": 'MUST_STASH_BECAUSE="urgent"; git stash'},
        }
        assert escape_hatch_used(hook_input) is True

    def test_true_when_marker_in_write_content(self) -> None:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/foo.py",
                "content": "# MUST_EXCEED_COMMENT_SIZE_BECAUSE: verbatim licence text\n",
            },
        }
        assert escape_hatch_used(hook_input) is True

    def test_true_when_marker_in_edit_new_string(self) -> None:
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/src/foo.py",
                "new_string": 'MUST_SCAN_ROOT_BECAUSE="explain why"; grep -rl x /',
            },
        }
        assert escape_hatch_used(hook_input) is True

    def test_false_when_no_marker(self) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
        assert escape_hatch_used(hook_input) is False

    def test_false_when_tool_input_missing(self) -> None:
        assert escape_hatch_used({"tool_name": "Bash"}) is False

    def test_false_when_hook_input_empty(self) -> None:
        assert escape_hatch_used({}) is False


class TestBuildVerdictLines:
    """build_verdict_lines turns per-handler decisions into JSONL-ready dicts."""

    def test_one_line_per_decision(self) -> None:
        decisions = [
            HandlerVerdict(handler="pipe_blocker", decision=Decision.DENY, terminal=True),
            HandlerVerdict(handler="absolute_path", decision=Decision.ALLOW, terminal=True),
        ]
        lines = build_verdict_lines(
            decisions=decisions,
            hook_input={"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
            event="PreToolUse",
            tool_name="Bash",
            session_id="sess-1",
        )
        assert len(lines) == 2
        assert {line["handler"] for line in lines} == {"pipe_blocker", "absolute_path"}

    def test_line_shape_and_values(self) -> None:
        decisions = [
            HandlerVerdict(
                handler="pipe_blocker", decision=Decision.DENY, terminal=True, rule="blacklisted"
            ),
        ]
        lines = build_verdict_lines(
            decisions=decisions,
            hook_input={"tool_name": "Bash", "tool_input": {"command": "npm test | tail"}},
            event="PreToolUse",
            tool_name="Bash",
            session_id="sess-1",
        )
        line = lines[0]
        assert line["session"] == "sess-1"
        assert line["event"] == "PreToolUse"
        assert line["tool"] == "Bash"
        assert line["handler"] == "pipe_blocker"
        assert line["verdict"] == "deny"
        assert line["rule"] == "blacklisted"
        assert line["mode"] == "block"
        assert line["overridden"] is False
        assert line.get("ts")

    def test_rule_defaults_to_none_in_line(self) -> None:
        decisions = [HandlerVerdict(handler="h1", decision=Decision.ALLOW, terminal=False)]
        lines = build_verdict_lines(
            decisions=decisions,
            hook_input={},
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
        )
        assert lines[0]["rule"] is None

    def test_mode_is_advisory_for_allow(self) -> None:
        decisions = [HandlerVerdict(handler="h1", decision=Decision.ALLOW, terminal=False)]
        lines = build_verdict_lines(
            decisions=decisions,
            hook_input={},
            event="PostToolUse",
            tool_name="Write",
            session_id="s",
        )
        assert lines[0]["mode"] == "advisory"

    def test_mode_is_block_for_ask(self) -> None:
        decisions = [HandlerVerdict(handler="h1", decision=Decision.ASK, terminal=True)]
        lines = build_verdict_lines(
            decisions=decisions,
            hook_input={},
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
        )
        assert lines[0]["mode"] == "block"

    def test_no_decisions_and_no_escape_hatch_yields_no_lines(self) -> None:
        lines = build_verdict_lines(
            decisions=[],
            hook_input={"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
        )
        assert lines == []

    def test_escape_hatch_adds_a_synthetic_overridden_line(self) -> None:
        """An escape hatch bypasses matches(), so the bypassed handler never
        appears in `decisions` for this event — the synthetic line is the
        only record that an override happened at all."""
        lines = build_verdict_lines(
            decisions=[],
            hook_input={
                "tool_name": "Bash",
                "tool_input": {"command": 'MUST_STASH_BECAUSE="urgent"; git stash'},
            },
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
        )
        assert len(lines) == 1
        synthetic = lines[0]
        assert synthetic["handler"] is None
        assert synthetic["overridden"] is True
        assert synthetic["verdict"] == "override"

    def test_escape_hatch_line_is_additional_to_real_decisions(self) -> None:
        decisions = [
            HandlerVerdict(handler="absolute_path", decision=Decision.ALLOW, terminal=True)
        ]
        lines = build_verdict_lines(
            decisions=decisions,
            hook_input={
                "tool_name": "Bash",
                "tool_input": {"command": 'MUST_STASH_BECAUSE="urgent"; git stash'},
            },
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
        )
        assert len(lines) == 2
        assert any(line["overridden"] for line in lines)
        assert any(not line["overridden"] for line in lines)


class TestStatusEventsAreNotRecorded:
    """Status renders drown the log, and carry no information (Plan 00234).

    Measured on this project's own log: 43,929 of 44,180 retained records
    (99.43%) were status-line renders, every one of them ``allow`` — a renderer
    has no other verdict it can return. Thirteen handlers at ~3,383 renders an
    hour filled the 10 MiB cap in **65 minutes**, so the log built to answer
    "which handlers earn their keep?" could only see one hour of one session.

    Excluding them leaves ~251 records/hour, stretching the same cap to roughly
    8 days. This is the DBF fix for the whole audit: without it, no removal can
    be verified against real firing data.
    """

    def _status_decisions(self) -> list[HandlerVerdict]:
        return [
            HandlerVerdict(handler="status-git-branch", decision=Decision.ALLOW, terminal=False),
            HandlerVerdict(handler="status-model-context", decision=Decision.ALLOW, terminal=False),
        ]

    def test_status_events_produce_no_lines_by_default(self) -> None:
        lines = build_verdict_lines(
            decisions=self._status_decisions(),
            hook_input={},
            event="Status",
            tool_name="",
            session_id="sess-1",
        )
        assert lines == []

    def test_status_events_are_recorded_when_explicitly_enabled(self) -> None:
        """The data is not forbidden, just off by default — debugging needs it."""
        lines = build_verdict_lines(
            decisions=self._status_decisions(),
            hook_input={},
            event="Status",
            tool_name="",
            session_id="sess-1",
            record_status_events=True,
        )
        assert len(lines) == 2

    def test_every_other_event_is_unaffected(self) -> None:
        """The filter is on the EVENT, so a handler named `status-*` elsewhere stays."""
        lines = build_verdict_lines(
            decisions=[
                HandlerVerdict(handler="status-thing", decision=Decision.ALLOW, terminal=False)
            ],
            hook_input={},
            event="PreToolUse",
            tool_name="Bash",
            session_id="sess-1",
        )
        assert len(lines) == 1

    def test_escape_hatch_in_a_status_event_is_still_dropped(self) -> None:
        """No synthetic override line either — a Status event records nothing."""
        lines = build_verdict_lines(
            decisions=[],
            hook_input={"tool_input": {"command": 'MUST_STASH_BECAUSE="x"; git stash'}},
            event="Status",
            tool_name="",
            session_id="sess-1",
        )
        assert lines == []


class TestAppendVerdicts:
    """append_verdicts writes JSONL lines to disk, fail-open, bounded by retention."""

    def test_disabled_writes_nothing(self, tmp_path: Path) -> None:
        result = append_verdicts(
            enabled=False,
            decisions=[HandlerVerdict(handler="h1", decision=Decision.DENY, terminal=True)],
            hook_input={},
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
            log_dir=tmp_path,
            max_bytes=1024,
        )
        assert result is None
        assert not (tmp_path / VERDICT_LOG_FILENAME).exists()

    def test_enabled_writes_jsonl_file(self, tmp_path: Path) -> None:
        result = append_verdicts(
            enabled=True,
            decisions=[HandlerVerdict(handler="h1", decision=Decision.DENY, terminal=True)],
            hook_input={},
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
            log_dir=tmp_path,
            max_bytes=1024 * 1024,
        )
        assert result == tmp_path / VERDICT_LOG_FILENAME
        lines = result.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["handler"] == "h1"

    def test_no_decisions_and_no_override_writes_nothing(self, tmp_path: Path) -> None:
        result = append_verdicts(
            enabled=True,
            decisions=[],
            hook_input={"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
            log_dir=tmp_path,
            max_bytes=1024,
        )
        assert result is None
        assert not (tmp_path / VERDICT_LOG_FILENAME).exists()

    def test_appends_across_calls(self, tmp_path: Path) -> None:
        for _ in range(3):
            append_verdicts(
                enabled=True,
                decisions=[HandlerVerdict(handler="h1", decision=Decision.ALLOW, terminal=False)],
                hook_input={},
                event="PreToolUse",
                tool_name="Bash",
                session_id="s",
                log_dir=tmp_path,
                max_bytes=1024 * 1024,
            )
        lines = (tmp_path / VERDICT_LOG_FILENAME).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    def test_creates_log_dir_if_missing(self, tmp_path: Path) -> None:
        target_dir = tmp_path / "nested" / "logs"
        append_verdicts(
            enabled=True,
            decisions=[HandlerVerdict(handler="h1", decision=Decision.ALLOW, terminal=False)],
            hook_input={},
            event="PreToolUse",
            tool_name="Bash",
            session_id="s",
            log_dir=target_dir,
            max_bytes=1024 * 1024,
        )
        assert (target_dir / VERDICT_LOG_FILENAME).exists()

    def test_retention_caps_the_file(self, tmp_path: Path) -> None:
        """A tight max_bytes budget triggers the shared retention primitive
        (Plan 00181's cap_log_file — the same rolling-sample mechanism as
        notifications.jsonl). verdicts.jsonl is a bounded ROLLING SAMPLE, not
        a durable lifetime counter (Plan 00209 Task 2.4 / Plan 00206 lesson):
        stats derived from it describe the retained window only."""
        for _ in range(50):
            append_verdicts(
                enabled=True,
                decisions=[HandlerVerdict(handler="h1", decision=Decision.ALLOW, terminal=False)],
                hook_input={},
                event="PreToolUse",
                tool_name="Bash",
                session_id="s",
                log_dir=tmp_path,
                max_bytes=200,
                retain_bytes=100,
            )
        size = (tmp_path / VERDICT_LOG_FILENAME).stat().st_size
        assert size <= 200
