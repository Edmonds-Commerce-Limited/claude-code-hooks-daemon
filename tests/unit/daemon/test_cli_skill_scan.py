"""Tests for the ``skill-scan`` CLI subcommand (Plan 00274)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_skill_scan
from claude_code_hooks_daemon.skill_scan.constants import STATE_FILE_NAME
from claude_code_hooks_daemon.skill_scan.state import load_state, record_success

_INVOKE_TARGET = "claude_code_hooks_daemon.skill_scan.invoker.ClaudeCliInvoker.invoke"
_EMPTY_SUGGESTIONS = '{"workloads": [], "corrections": []}'


def _args(
    project_root: Path,
    force: bool = False,
    dry_run: bool = False,
    window_days: int | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        force=force,
        dry_run=dry_run,
        window_days=window_days,
    )


def _scaffold(tmp_path: Path, enabled: bool = False) -> Path:
    """Project with config and a transcript fixture wired via transcript_dir."""
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    lines = [
        json.dumps(
            {
                "type": "user",
                "sessionId": f"s{i}",
                "message": {"role": "user", "content": "regenerate docs then restart daemon"},
            }
        )
        for i in range(3)
    ]
    (transcripts / "a.jsonl").write_text("\n".join(lines) + "\n")
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        "handlers:\n"
        "  session_start:\n"
        "    skill_opportunity_detector:\n"
        f"      enabled: {str(enabled).lower()}\n"
        "      priority: 61\n"
        "      options:\n"
        "        check_interval_days: 7\n"
        f"        transcript_dir: {transcripts}\n"
    )
    return root


def _state_path(root: Path) -> Path:
    return root / ".claude" / "hooks-daemon" / "untracked" / STATE_FILE_NAME


class TestCmdSkillScan:
    def test_runs_with_handler_disabled(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        # Decision 5: a manual run is consent; `enabled` gates only the advisory.
        root = _scaffold(tmp_path, enabled=False)
        with patch(_INVOKE_TARGET, return_value=(_EMPTY_SUGGESTIONS, None)):
            assert cmd_skill_scan(_args(root, force=True)) == 0
        out = capsys.readouterr().out
        assert "Report written" in out
        report = root / "untracked" / "reports"
        assert any(report.iterdir())

    def test_success_records_scan_state(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        with patch(_INVOKE_TARGET, return_value=(_EMPTY_SUGGESTIONS, None)):
            cmd_skill_scan(_args(root, force=True))
        state = load_state(_state_path(root))
        assert state.last_scan_at is not None
        assert state.last_report_path is not None

    def test_ttl_gate_skips_recent_scan(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        record_success(_state_path(root), report_path="/r.md")
        with patch(_INVOKE_TARGET, return_value=(_EMPTY_SUGGESTIONS, None)) as invoke:
            assert cmd_skill_scan(_args(root)) == 0
        assert invoke.call_count == 0
        assert "not due" in capsys.readouterr().out

    def test_force_bypasses_ttl(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        record_success(_state_path(root), report_path="/r.md")
        with patch(_INVOKE_TARGET, return_value=(_EMPTY_SUGGESTIONS, None)) as invoke:
            assert cmd_skill_scan(_args(root, force=True)) == 0
        assert invoke.call_count == 1

    def test_dry_run_prints_digest_no_model_no_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        with patch(_INVOKE_TARGET, return_value=(_EMPTY_SUGGESTIONS, None)) as invoke:
            assert cmd_skill_scan(_args(root, dry_run=True)) == 0
        assert invoke.call_count == 0
        out = capsys.readouterr().out
        assert "regenerate docs" in out
        assert not _state_path(root).exists()

    def test_model_failure_exits_zero_with_partial_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        with patch(_INVOKE_TARGET, return_value=(None, "claude CLI not found on PATH")):
            assert cmd_skill_scan(_args(root, force=True)) == 0
        out = capsys.readouterr().out
        assert "skipped" in out
        state = load_state(_state_path(root))
        assert state.last_scan_at is None
        assert state.last_attempt_at is not None

    def test_empty_window_is_successful_noop(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        with patch(_INVOKE_TARGET, return_value=(_EMPTY_SUGGESTIONS, None)) as invoke:
            assert cmd_skill_scan(_args(root, force=True, window_days=0)) == 0
        assert invoke.call_count == 0
        state = load_state(_state_path(root))
        assert state.last_scan_at is not None
