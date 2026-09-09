"""Tests for the cmd_check_config_migrations CLI command's offload (Plan 00329).

The advisory exits 1 whenever it has suggestions, and Claude Code delivers
an exit-1 Bash result head-and-tail with the middle dropped past ~10,000
characters; so by default the full advisory goes to a file and stdout is a
bounded summary. ``--full`` restores the inline form.
"""

import argparse
import json
from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.daemon.cli import cmd_check_config_migrations
from claude_code_hooks_daemon.install.report_offload import SUMMARY_MAX_BYTES

_MANIFEST = """\
version: "2.13.0"
date: "2026-02-17"
breaking: false
config_changes:
  added:
    - key: handlers.post_tool_use.recovery_cron_advisor.enabled
      description: "Opt-in failsafe recovery cron advisory"
      recommended: true
      dormant: true
      recommended_value: true
    - key: daemon.enforce_single_daemon_process
      description: "Prevents multiple daemon instances"
  renamed: []
  removed: []
  changed: []
"""


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    md = tmp_path / "manifests"
    md.mkdir()
    (md / "v2.13.0.yaml").write_text(_MANIFEST)
    cfg = tmp_path / "hooks-daemon.yaml"
    cfg.write_text(yaml.dump({"handlers": {}, "daemon": {}}))
    return md, cfg


def _args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    md, cfg = _fixture(tmp_path)
    defaults: dict[str, object] = {
        "from_version": "2.12.0",
        "to_version": "2.13.0",
        "config": str(cfg),
        "format": "text",
        "manifests_dir": str(md),
        "report_dir": str(tmp_path / "reports"),
        "full": False,
        "project_root": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdCheckConfigMigrationsOffload:
    def test_default_prints_bounded_summary_and_writes_advisory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_check_config_migrations(_args(tmp_path)) == 1
        out = capsys.readouterr().out
        assert len(out.encode("utf-8")) <= SUMMARY_MAX_BYTES
        assert "ADVISORY.md" in out
        assert "recovery_cron_advisor.enabled = true" in out
        assert "Prevents multiple daemon instances" not in out
        advisory = tmp_path / "reports" / "v2.12.0-to-v2.13.0" / "ADVISORY.md"
        assert "Prevents multiple daemon instances" in advisory.read_text(encoding="utf-8")

    def test_full_flag_prints_everything_inline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_check_config_migrations(_args(tmp_path, full=True)) == 1
        out = capsys.readouterr().out
        assert "Prevents multiple daemon instances" in out
        assert not (tmp_path / "reports").exists()

    def test_unwritable_report_dir_falls_back_to_inline_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        assert cmd_check_config_migrations(_args(tmp_path, report_dir=str(blocker / "r"))) == 1
        captured = capsys.readouterr()
        assert "Prevents multiple daemon instances" in captured.out
        assert "WARNING" in captured.err
        assert "inline" in captured.err

    def test_json_carries_report_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_check_config_migrations(_args(tmp_path, format="json"))
        payload = json.loads(capsys.readouterr().out)
        assert Path(payload["report_path"]).is_file()

    def test_clean_config_returns_zero_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_check_config_migrations(_args(tmp_path, from_version="2.13.0")) == 0
        assert "No Changes Needed" in capsys.readouterr().out
        assert not (tmp_path / "reports").exists()
