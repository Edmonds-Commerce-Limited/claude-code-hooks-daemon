"""Tests for the hand-probe helper behind ``hooks-daemon probe`` (Plan 00466 N12).

The defect this closes: the Plan 00467 plugin audit fed hand-built PreToolUse
payloads through ``.claude/hooks/pre-tool-use`` to read handler verdicts. The
payloads carried no ``synthetic_source`` and their session ids matched no
known synthetic shape, so ``verdicts.jsonl`` recorded them as REAL agent
traffic — including the orchestrator-simulate records Plan 00418's
enforcement decision is read from. Nothing told a prober to mark the event,
and nothing marked it for them.

The helper marks it for them. These tests pin three things:

1. The event the helper sends carries the documented marker, and a caller's
   own marker survives.
2. That event, once it reaches the daemon, is written to ``verdicts.jsonl``
   as synthetic — proved through the real controller, not by re-reading the
   marker off the dict we built.
3. An unmarked hand-sent payload is still REAL. The helper must not widen
   the classifier: guessing "synthetic" for unmarked traffic would discard an
   agent's own records on no evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from claude_code_hooks_daemon.config.models import VerdictLogConfig
from claude_code_hooks_daemon.constants.events import EventID
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_probe
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.daemon.hook_probe import (
    ProbeInputError,
    ProbeOutcome,
    build_probe_event,
    entry_point_for,
    render_verdict,
    resolve_probe_event,
)
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    MANUAL_PROBE,
    SYNTHETIC_SOURCE_FIELD,
    record_synthetic_source,
)

_BASH_PAYLOAD: dict[str, Any] = {
    "tool_name": "Bash",
    "tool_input": {"command": "git push --force origin main"},
}

#: A fake entry point: records exactly what it was sent, then answers as the
#: daemon would. Run with ``bash``, so it needs no executable bit.
_CAPTURING_ENTRY_POINT = """#!/bin/bash
cat > "$(dirname "$0")/captured.json"
printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"fake handler says no"}}'
"""


def _project_with_entry_point(root: Path, bash_key: str, script: str) -> Path:
    hooks_dir = root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    entry = hooks_dir / bash_key
    entry.write_text(script, encoding="utf-8")
    return entry


class TestResolveProbeEvent:
    """The event can be named the way each surface already names it."""

    @pytest.mark.parametrize("name", ["PreToolUse", "pre-tool-use", "pre_tool_use"])
    def test_every_spelling_resolves_to_the_same_event(self, name: str) -> None:
        assert resolve_probe_event(name) is EventID.PRE_TOOL_USE

    def test_the_status_line_wire_name_resolves(self) -> None:
        """``Status`` is the wire name, ``StatusLine`` the json key."""
        assert resolve_probe_event("Status") is EventID.STATUS_LINE
        assert resolve_probe_event("status-line") is EventID.STATUS_LINE

    def test_an_unknown_event_is_refused_and_lists_the_valid_ones(self) -> None:
        with pytest.raises(ProbeInputError, match="PreToolUse"):
            resolve_probe_event("NotAnEvent")


class TestBuildProbeEvent:
    def _build(self, payload: object, tmp_path: Path) -> dict[str, Any]:
        return build_probe_event(
            payload,
            event=EventID.PRE_TOOL_USE,
            project_root=tmp_path,
            session_id="manual-probe-fixed",
        )

    def test_an_unmarked_payload_is_marked_with_the_documented_value(self, tmp_path: Path) -> None:
        event = self._build(dict(_BASH_PAYLOAD), tmp_path)
        assert event[SYNTHETIC_SOURCE_FIELD] == MANUAL_PROBE == "manual-probe"

    def test_a_caller_marked_payload_keeps_its_own_value(self, tmp_path: Path) -> None:
        """The producer knows what it is; the helper must not overwrite that."""
        payload = {**_BASH_PAYLOAD, SYNTHETIC_SOURCE_FIELD: "plugin-audit"}
        assert self._build(payload, tmp_path)[SYNTHETIC_SOURCE_FIELD] == "plugin-audit"

    @pytest.mark.parametrize("bad_marker", ["", 7, None, ["x"]])
    def test_a_marker_the_classifier_would_ignore_is_refused(
        self, bad_marker: object, tmp_path: Path
    ) -> None:
        """Keeping it would send a probe the log records as REAL — the defect."""
        payload = {**_BASH_PAYLOAD, SYNTHETIC_SOURCE_FIELD: bad_marker}
        with pytest.raises(ProbeInputError, match=SYNTHETIC_SOURCE_FIELD):
            self._build(payload, tmp_path)

    def test_missing_framing_is_filled_in_like_claude_code_sends_it(self, tmp_path: Path) -> None:
        event = self._build(dict(_BASH_PAYLOAD), tmp_path)
        assert event["hook_event_name"] == "PreToolUse"
        assert event["session_id"] == "manual-probe-fixed"
        assert event["cwd"] == str(tmp_path)
        assert event["tool_input"] == _BASH_PAYLOAD["tool_input"]

    def test_caller_framing_is_kept(self, tmp_path: Path) -> None:
        """A prober testing a repeat fire needs to choose the session."""
        payload = {**_BASH_PAYLOAD, "session_id": "mine", "cwd": "/elsewhere"}
        event = self._build(payload, tmp_path)
        assert event["session_id"] == "mine"
        assert event["cwd"] == "/elsewhere"

    def test_the_callers_dict_is_not_mutated(self, tmp_path: Path) -> None:
        payload = dict(_BASH_PAYLOAD)
        self._build(payload, tmp_path)
        assert SYNTHETIC_SOURCE_FIELD not in payload

    def test_a_non_object_payload_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ProbeInputError, match="JSON object"):
            self._build(["not", "an", "object"], tmp_path)

    def test_a_payload_naming_another_event_is_refused(self, tmp_path: Path) -> None:
        """It would reach the PreToolUse entry point claiming to be a Stop."""
        payload = {**_BASH_PAYLOAD, "hook_event_name": "Stop"}
        with pytest.raises(ProbeInputError, match="Stop"):
            self._build(payload, tmp_path)


class TestEntryPointFor:
    def test_names_the_projects_forwarder_for_the_event(self, tmp_path: Path) -> None:
        entry = _project_with_entry_point(tmp_path, "pre-tool-use", "#!/bin/bash\n")
        assert entry_point_for(tmp_path, EventID.PRE_TOOL_USE) == entry

    def test_a_missing_forwarder_is_refused_by_path(self, tmp_path: Path) -> None:
        with pytest.raises(ProbeInputError, match=r"\.claude/hooks/pre-tool-use"):
            entry_point_for(tmp_path, EventID.PRE_TOOL_USE)


_RENDERED_EVENT: dict[str, Any] = {
    **_BASH_PAYLOAD,
    SYNTHETIC_SOURCE_FIELD: MANUAL_PROBE,
    "session_id": "manual-probe-abc",
}


class TestRenderVerdict:
    def _render(self, outcome: ProbeOutcome, event: Any = EventID.PRE_TOOL_USE) -> tuple[int, str]:
        return render_verdict(
            event=event,
            entry_point=Path("/p/.claude/hooks/pre-tool-use"),
            hook_event=_RENDERED_EVENT,
            outcome=outcome,
        )

    def test_a_deny_is_reported_with_its_reason_and_the_marker(self) -> None:
        response = {
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": "no force push",
            }
        }
        code, text = self._render(ProbeOutcome(0, json.dumps(response), ""))
        assert code == 0
        assert "decision: deny" in text
        assert "no force push" in text
        assert f"{SYNTHETIC_SOURCE_FIELD}: {MANUAL_PROBE}" in text
        assert "session_id: manual-probe-abc" in text

    def test_an_empty_response_is_an_allow(self) -> None:
        code, text = self._render(ProbeOutcome(0, "{}", ""))
        assert code == 0
        assert "decision: allow" in text

    def test_a_stop_block_is_read_from_the_json_not_the_exit_code(self) -> None:
        """The Stop forwarder exits 2 on a block; that is a verdict, not a failure."""
        response = {"decision": "block", "reason": "explain yourself"}
        code, text = self._render(ProbeOutcome(2, json.dumps(response), "explain yourself"))
        assert code == 0
        assert "decision: block" in text

    def test_an_unreachable_daemon_is_a_failure_not_a_verdict(self) -> None:
        stderr = "HOOKS DAEMON ERROR [daemon_startup_failed]: could not start"
        code, text = self._render(ProbeOutcome(0, "{}", stderr))
        assert code == 1
        assert "daemon_startup_failed" in text
        assert "decision:" not in text

    def test_a_daemon_rejection_is_a_failure_not_an_allow(self) -> None:
        """A schema refusal carries no decision; reading it as allow is vacuous."""
        response = {"error": "invalid_request", "details": ["tool_response required"]}
        code, text = self._render(ProbeOutcome(0, json.dumps(response), ""))
        assert code == 1
        assert "tool_response required" in text

    def test_a_non_json_response_is_a_failure(self) -> None:
        code, text = self._render(ProbeOutcome(0, "not json", ""))
        assert code == 1
        assert "not json" in text

    def test_a_scoped_event_carries_the_note_that_scoped_handlers_did_not_answer(
        self,
    ) -> None:
        """Measured: a marked Stop probe answered `{}` where the unmarked one
        was blocked, because `auto_continue_stop` is scoped MAIN. An allow that
        does not say so reads as a working handler passing."""
        code, text = self._render(ProbeOutcome(0, "{}", ""), event=EventID.STOP)
        assert code == 0
        assert "MAIN" in text
        assert "SUB" in text

    def test_an_event_without_agent_scope_carries_no_note(self) -> None:
        code, text = self._render(ProbeOutcome(0, "{}", ""), event=EventID.SESSION_START)
        assert code == 0
        assert "MAIN" not in text

    def test_a_raw_stdout_event_prints_its_raw_answer(self) -> None:
        code, text = self._render(ProbeOutcome(0, "Opus | 42%", ""), event=EventID.STATUS_LINE)
        assert code == 0
        assert "Opus | 42%" in text


class TestCmdProbe:
    """The CLI verb sends the marked event through the entry point."""

    def _args(self, root: Path, **overrides: Any) -> argparse.Namespace:
        values: dict[str, Any] = {
            "project_root": root,
            "event": "PreToolUse",
            "json": json.dumps(_BASH_PAYLOAD),
            "file": None,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_the_entry_point_receives_the_marked_payload(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entry = _project_with_entry_point(tmp_path, "pre-tool-use", _CAPTURING_ENTRY_POINT)

        assert cmd_probe(self._args(tmp_path)) == 0

        sent = json.loads((entry.parent / "captured.json").read_text(encoding="utf-8"))
        assert sent[SYNTHETIC_SOURCE_FIELD] == MANUAL_PROBE
        assert sent["tool_input"] == _BASH_PAYLOAD["tool_input"]
        out = capsys.readouterr().out
        assert "decision: deny" in out
        assert "fake handler says no" in out

    def test_a_payload_file_is_read(self, tmp_path: Path) -> None:
        entry = _project_with_entry_point(tmp_path, "pre-tool-use", _CAPTURING_ENTRY_POINT)
        payload_file = tmp_path / "payload.json"
        payload_file.write_text(json.dumps(_BASH_PAYLOAD), encoding="utf-8")

        assert cmd_probe(self._args(tmp_path, json=None, file=payload_file)) == 0

        sent = json.loads((entry.parent / "captured.json").read_text(encoding="utf-8"))
        assert sent[SYNTHETIC_SOURCE_FIELD] == MANUAL_PROBE

    def test_a_caller_marker_reaches_the_entry_point_unchanged(self, tmp_path: Path) -> None:
        entry = _project_with_entry_point(tmp_path, "pre-tool-use", _CAPTURING_ENTRY_POINT)
        payload = {**_BASH_PAYLOAD, SYNTHETIC_SOURCE_FIELD: "plugin-audit"}

        assert cmd_probe(self._args(tmp_path, json=json.dumps(payload))) == 0

        sent = json.loads((entry.parent / "captured.json").read_text(encoding="utf-8"))
        assert sent[SYNTHETIC_SOURCE_FIELD] == "plugin-audit"

    def test_invalid_json_is_a_usage_error_and_sends_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        entry = _project_with_entry_point(tmp_path, "pre-tool-use", _CAPTURING_ENTRY_POINT)

        assert cmd_probe(self._args(tmp_path, json="{not json")) == 2

        assert not (entry.parent / "captured.json").exists()
        assert "not valid JSON" in capsys.readouterr().err

    def test_a_missing_entry_point_is_a_usage_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_probe(self._args(tmp_path)) == 2
        assert "pre-tool-use" in capsys.readouterr().err


class TestTheVerdictLogRecordsTheProbe:
    """End to end through the real controller into ``verdicts.jsonl``.

    This is the log ``synthetic_traffic`` classifies, and the one Plan 00418's
    enforcement decision is read from. Asserting on the dict the helper built
    would only prove the helper agrees with itself.
    """

    def teardown_method(self) -> None:
        ProjectContext.reset()

    @pytest.fixture
    def workspace_root(self, tmp_path: Path) -> Path:
        workspace = tmp_path / "test-workspace"
        claude_dir = workspace / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "hooks-daemon.yaml").write_text(
            "version: '1.0'\n"
            "daemon:\n"
            "  idle_timeout_seconds: 600\n"
            "  log_level: INFO\n"
            "handlers:\n"
            "  pre_tool_use: {}\n"
        )
        return workspace

    def _controller(self, workspace_root: Path) -> DaemonController:
        controller = DaemonController()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0, stdout="/tmp/test\n"),
                Mock(returncode=0, stdout="git@github.com:test/repo.git\n"),
                Mock(returncode=0, stdout="/tmp/test\n"),
            ]
            controller.initialise(workspace_root=workspace_root, verdict_log=VerdictLogConfig())
        return controller

    def _records(self, workspace_root: Path, hook_input: dict[str, Any]) -> list[dict[str, Any]]:
        controller = self._controller(workspace_root)
        controller.process_request({"event": "PreToolUse", "hook_input": hook_input})
        log = (
            workspace_root
            / ".claude"
            / "hooks-daemon"
            / "untracked"
            / "logs"
            / "hooks"
            / "verdicts.jsonl"
        )
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        assert records, "the probe matched no handler, so the test proves nothing"
        return records

    def test_a_helper_built_event_is_recorded_as_synthetic(self, workspace_root: Path) -> None:
        hook_input = build_probe_event(
            dict(_BASH_PAYLOAD),
            event=EventID.PRE_TOOL_USE,
            project_root=workspace_root,
            session_id="plugin-audit-probe",
        )
        for record in self._records(workspace_root, hook_input):
            assert record_synthetic_source(record) == MANUAL_PROBE

    def test_an_unmarked_hand_sent_payload_is_still_recorded_as_real(
        self, workspace_root: Path
    ) -> None:
        """The N12 shape exactly: no marker, a session id no rule recognises."""
        hook_input = {
            **_BASH_PAYLOAD,
            "hook_event_name": "PreToolUse",
            "session_id": "plugin-audit-probe",
        }
        for record in self._records(workspace_root, hook_input):
            assert record_synthetic_source(record) is None
