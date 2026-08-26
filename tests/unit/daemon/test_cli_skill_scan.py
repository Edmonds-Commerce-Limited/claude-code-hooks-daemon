"""Tests for the ``skill-scan`` CLI subcommand (Plan 00274)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_skill_scan
from claude_code_hooks_daemon.skill_scan.constants import STATE_FILE_NAME
from claude_code_hooks_daemon.skill_scan.state import load_state, record_success


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
    def test_runs_with_handler_disabled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Decision 5: a manual run is consent; `enabled` gates only the advisory.
        root = _scaffold(tmp_path, enabled=False)
        assert cmd_skill_scan(_args(root, force=True)) == 0
        out = capsys.readouterr().out
        assert "Report written" in out
        assert "dispatch a subagent" in out
        report = root / "untracked" / "reports"
        assert any(report.iterdir())

    def test_report_embeds_judging_prompt(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_skill_scan(_args(root, force=True)) == 0
        report_dir = root / "untracked" / "reports"
        report_text = next(report_dir.iterdir()).read_text()
        assert "## Judging (subagent task)" in report_text
        assert "You are analysing clustered human prompts" in report_text
        assert "## Findings" in report_text

    def test_success_records_scan_state(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        cmd_skill_scan(_args(root, force=True))
        state = load_state(_state_path(root))
        assert state.last_scan_at is not None
        assert state.last_report_path is not None

    def test_ttl_gate_skips_recent_scan(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        record_success(_state_path(root), report_path="/r.md")
        assert cmd_skill_scan(_args(root)) == 0
        assert "not due" in capsys.readouterr().out
        assert not (root / "untracked" / "reports").exists()

    def test_force_bypasses_ttl(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        record_success(_state_path(root), report_path="/r.md")
        assert cmd_skill_scan(_args(root, force=True)) == 0
        assert any((root / "untracked" / "reports").iterdir())

    def test_dry_run_prints_digest_no_report_no_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_skill_scan(_args(root, dry_run=True)) == 0
        out = capsys.readouterr().out
        assert "regenerate docs" in out
        assert not _state_path(root).exists()
        assert not (root / "untracked" / "reports").exists()

    def test_empty_window_warns_and_records_attempt_only(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # An empty window must NOT silence the advisory for the whole
        # interval — a mistyped transcript_dir would look identical. The CLI
        # warns (naming the directory read) and records only an attempt.
        root = _scaffold(tmp_path)
        assert cmd_skill_scan(_args(root, force=True, window_days=0)) == 0
        out = capsys.readouterr().out
        assert "WARNING: no genuine prompts" in out
        assert str(tmp_path / "transcripts") in out
        state = load_state(_state_path(root))
        assert state.last_scan_at is None
        assert state.last_attempt_at is not None
