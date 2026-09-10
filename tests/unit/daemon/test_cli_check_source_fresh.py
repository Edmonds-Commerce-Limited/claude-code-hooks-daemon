"""Tests for `bin/hooks-daemon check-source-fresh` (Plan 00371).

Covers `cmd_check_source_fresh`: exits 0 against a fresh daemon, 1 against a
stale or unreachable one, naming the reason in each non-zero case. Mirrors
the fixture/patching style of the sibling `TestCmdHealth` in
`test_cli_additional_commands.py`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_check_source_fresh, main
from claude_code_hooks_daemon.daemon.source_fingerprint import (
    compute_current_project_fingerprint,
)


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: Any) -> None:
    """Mock git repository checks for tests running in tmp directories."""

    def mock_get_git_repo_name(project_root: Path) -> str:
        return "test-repo"

    def mock_get_git_toplevel(project_root: Path) -> Path:
        return project_root

    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_repo_name",
        mock_get_git_repo_name,
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_toplevel",
        mock_get_git_toplevel,
    )


@pytest.fixture(autouse=True)
def reset_project_context() -> None:
    """Reset ProjectContext singleton between tests."""
    ProjectContext._initialized = False


def _make_project(tmp_path: Path) -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon").mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\n")
    return tmp_path


class TestCmdCheckSourceFresh:
    """Tests for cmd_check_source_fresh command."""

    def test_daemon_not_running(self, tmp_path: Path) -> None:
        """Returns 1 when no daemon is running -- freshness cannot be verified."""
        project_path = _make_project(tmp_path)
        args = argparse.Namespace(project_root=project_path)

        with patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None):
            result = cmd_check_source_fresh(args)

        assert result == 1

    def test_fresh_daemon_exits_zero(self, tmp_path: Path) -> None:
        """A daemon reporting the same fingerprint as the working tree is fresh."""
        project_path = _make_project(tmp_path)
        args = argparse.Namespace(project_root=project_path)
        current = compute_current_project_fingerprint(project_path)
        mock_response = {"result": {"source_fingerprint": current}}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_check_source_fresh(args)

        assert result == 0

    def test_stale_daemon_exits_one(self, tmp_path: Path) -> None:
        """A daemon reporting a DIFFERENT fingerprint than the working tree is stale."""
        project_path = _make_project(tmp_path)
        args = argparse.Namespace(project_root=project_path)
        mock_response = {"result": {"source_fingerprint": "0" * 64}}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_check_source_fresh(args)

        assert result == 1

    def test_no_response_exits_one(self, tmp_path: Path) -> None:
        """The daemon does not answer the health request at all."""
        project_path = _make_project(tmp_path)
        args = argparse.Namespace(project_root=project_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=None,
            ),
        ):
            result = cmd_check_source_fresh(args)

        assert result == 1

    def test_response_with_no_fingerprint_exits_one(self, tmp_path: Path) -> None:
        """A daemon predating Plan 00371 (health has no source_fingerprint key)."""
        project_path = _make_project(tmp_path)
        args = argparse.Namespace(project_root=project_path)
        mock_response = {"result": {"status": "healthy"}}

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value=mock_response,
            ),
        ):
            result = cmd_check_source_fresh(args)

        assert result == 1

    def test_error_response_exits_one(self, tmp_path: Path) -> None:
        """A daemon-side error response is treated the same as no response."""
        project_path = _make_project(tmp_path)
        args = argparse.Namespace(project_root=project_path)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                return_value={"error": "boom"},
            ),
        ):
            result = cmd_check_source_fresh(args)

        assert result == 1


class TestCheckSourceFreshSubcommandRegistered:
    """The CLI parser actually wires `check-source-fresh` to the command."""

    def test_main_dispatches_to_cmd_check_source_fresh(self, tmp_path: Path) -> None:
        """main() routes the `check-source-fresh` subcommand correctly."""
        project_path = _make_project(tmp_path)

        with (
            patch(
                "sys.argv",
                [
                    "claude-hooks-daemon",
                    "--project-root",
                    str(project_path),
                    "check-source-fresh",
                ],
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.cmd_check_source_fresh",
                return_value=0,
            ) as mock_check,
        ):
            result = main()

        assert result == 0
        mock_check.assert_called_once()
