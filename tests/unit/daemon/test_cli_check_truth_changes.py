"""Tests for the cmd_check_truth_changes CLI command (Plan 00118).

Covers the argparse-facing command wrapper: text/json output, exit codes
(0 none / 1 changes / 2 error), and the known-versions hint on a bad range.
"""

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_check_truth_changes


def _make_truth_dir(tmp_path: Path) -> Path:
    d = tmp_path / "truth-changes"
    d.mkdir(parents=True, exist_ok=True)
    (d / "v3.16.0.yaml").write_text(
        "version: '3.16.0'\n"
        "truth_changes:\n"
        "  - was: Scan the CLAUDE/Plan folder for the next number.\n"
        "    now: Read git config --local hooksdaemon.latestPlanNumber and add one.\n"
    )
    return d


def _args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "from_version": "3.15.0",
        "to_version": "3.17.0",
        "format": "text",
        "truth_changes_dir": str(_make_truth_dir(tmp_path)),
        "report_dir": None,
        # Inline by default so the pre-offload assertions keep reading the
        # report from stdout; naming a report_dir opts a test into the offload.
        "full": "report_dir" not in overrides,
        "project_root": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCmdCheckTruthChanges:
    def test_text_output_returns_one_when_changes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_check_truth_changes(_args(tmp_path))
        assert result == 1
        out = capsys.readouterr().out
        assert "hooksdaemon.latestPlanNumber" in out
        assert "Truth-Changes to reconcile" in out

    def test_json_output_returns_one_when_changes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_check_truth_changes(_args(tmp_path, format="json"))
        assert result == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["has_changes"] is True
        assert payload["changes"][0]["version"] == "3.16.0"

    def test_returns_zero_when_no_changes_in_range(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_check_truth_changes(
            _args(tmp_path, from_version="3.16.0", to_version="3.16.0")
        )
        assert result == 0
        assert "No truth-changes" in capsys.readouterr().out

    def test_invalid_range_returns_two_and_lists_known_versions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_check_truth_changes(
            _args(tmp_path, from_version="3.18.0", to_version="3.16.0")
        )
        assert result == 2
        err = capsys.readouterr().err
        assert "ERROR" in err
        # The known-versions hint surfaces the available manifest version
        assert "3.16.0" in err

    def test_missing_truth_changes_dir_attr_uses_default(self) -> None:
        # No truth_changes_dir attribute => falls back to the packaged default dir.
        args = argparse.Namespace(
            from_version="3.16.0", to_version="3.16.0", format="text", full=True
        )
        result = cmd_check_truth_changes(args)
        # Equal from/to => empty range => exit 0 regardless of the default dir.
        assert result == 0


class TestCmdCheckTruthChangesOffload:
    """Plan 00329: stdout is the bounded summary; the report goes to a file."""

    def test_report_dir_prints_the_summary_and_writes_the_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_check_truth_changes(_args(tmp_path, report_dir=str(tmp_path / "reports")))
        assert result == 1
        out = capsys.readouterr().out
        assert "Truth-Changes to reconcile" in out
        assert "hooksdaemon.latestPlanNumber" not in out
        assert "REPORT.md" in out
        report = tmp_path / "reports" / "v3.15.0-to-v3.17.0" / "REPORT.md"
        assert report.is_file()
        assert "hooksdaemon.latestPlanNumber" in report.read_text(encoding="utf-8")

    def test_full_flag_keeps_the_whole_report_inline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = cmd_check_truth_changes(
            _args(tmp_path, report_dir=str(tmp_path / "reports"), full=True)
        )
        assert result == 1
        out = capsys.readouterr().out
        assert "hooksdaemon.latestPlanNumber" in out
        assert not (tmp_path / "reports").exists()

    def test_unwritable_report_dir_falls_back_to_inline_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        result = cmd_check_truth_changes(_args(tmp_path, report_dir=str(blocker / "reports")))
        assert result == 1
        captured = capsys.readouterr()
        assert "hooksdaemon.latestPlanNumber" in captured.out
        assert "WARNING" in captured.err
        assert "inline" in captured.err

    def test_json_carries_report_path_and_chunks(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_check_truth_changes(_args(tmp_path, format="json", report_dir=str(tmp_path / "r")))
        payload = json.loads(capsys.readouterr().out)
        assert Path(payload["report_path"]).is_file()
        assert payload["chunks"][0]["key"] == "unassigned"


class TestReportOffloadHonoursGlobalProjectRoot:
    """The wrapper passes --project-root BEFORE the subcommand; it must survive."""

    def _namespace_for(self, argv: list[str]) -> argparse.Namespace:
        from unittest.mock import patch

        from claude_code_hooks_daemon.daemon import cli

        seen: list[argparse.Namespace] = []

        def capture(args: argparse.Namespace) -> int:
            seen.append(args)
            return 0

        with (
            patch("sys.argv", ["claude-hooks-daemon", *argv]),
            patch.object(cli, "cmd_check_truth_changes", capture),
            patch.object(cli, "cmd_check_config_migrations", capture),
        ):
            cli.main()
        assert len(seen) == 1
        return seen[0]

    def test_global_project_root_is_not_clobbered_by_the_subcommand(self, tmp_path: Path) -> None:
        args = self._namespace_for(
            ["--project-root", str(tmp_path), "check-truth-changes", "--from", "1", "--to", "2"]
        )
        assert args.project_root == tmp_path

    def test_subcommand_project_root_wins_when_given(self, tmp_path: Path) -> None:
        args = self._namespace_for(
            [
                "--project-root",
                str(tmp_path / "global"),
                "check-config-migrations",
                "--from",
                "1",
                "--to",
                "2",
                "--project-root",
                str(tmp_path / "local"),
            ]
        )
        assert args.project_root == tmp_path / "local"
