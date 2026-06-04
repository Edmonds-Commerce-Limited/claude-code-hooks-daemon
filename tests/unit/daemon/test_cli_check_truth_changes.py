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
        args = argparse.Namespace(from_version="3.16.0", to_version="3.16.0", format="text")
        result = cmd_check_truth_changes(args)
        # Equal from/to => empty range => exit 0 regardless of the default dir.
        assert result == 0
