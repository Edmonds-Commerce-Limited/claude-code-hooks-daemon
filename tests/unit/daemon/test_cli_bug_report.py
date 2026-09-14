"""Tests for the bug-report CLI command.

Tests cover:
- Report generation with all required sections
- Description included in report
- Default output path creation
- --output flag overrides output path
- --output - prints to stdout
- Graceful handling when daemon not running
- Graceful handling when config missing
"""

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import _BUG_REPORT_LOG_LINES, cmd_bug_report
from claude_code_hooks_daemon.utils.report_scrubbing import PROJECT_ROOT_PLACEHOLDER


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
    """Create minimal project structure for testing."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    hooks_daemon_dir = claude_dir / "hooks-daemon"
    hooks_daemon_dir.mkdir()
    untracked_dir = hooks_daemon_dir / "untracked"
    untracked_dir.mkdir()

    config_file = claude_dir / "hooks-daemon.yaml"
    config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")
    return tmp_path


def _make_args(
    project_root: Path,
    output: str | None = None,
    description: str = "test bug",
) -> argparse.Namespace:
    """Create argparse.Namespace for bug-report command."""
    return argparse.Namespace(
        project_root=project_root,
        pid_file=None,
        socket=None,
        output=output,
        description=description,
    )


class TestBugReportDaemonNotRunning:
    """Tests for bug-report when daemon is not running."""

    def test_still_generates_report(self, tmp_path: Path) -> None:
        """Bug report generates even when daemon is not running."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file), description="daemon crashed")

        result = cmd_bug_report(args)

        assert result == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "daemon crashed" in content

    def test_report_shows_daemon_not_running(self, tmp_path: Path) -> None:
        """Report indicates daemon is not running."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "NOT RUNNING" in content


class TestBugReportSections:
    """Tests for required report sections."""

    def test_contains_header(self, tmp_path: Path) -> None:
        """Report contains header with description and timestamp."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file), description="my bug")

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "# Bug Report" in content
        assert "my bug" in content
        assert "Generated:" in content

    def test_contains_version_section(self, tmp_path: Path) -> None:
        """Report contains daemon version info."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "## Daemon Version" in content

    def test_contains_system_info(self, tmp_path: Path) -> None:
        """Report contains system information."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "## System Info" in content
        assert "Python:" in content

    def test_contains_daemon_status(self, tmp_path: Path) -> None:
        """Report contains daemon status section."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "## Daemon Status" in content

    def test_contains_configuration(self, tmp_path: Path) -> None:
        """Report contains configuration section with config contents."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "## Configuration" in content
        assert "log_level" in content

    def test_contains_handlers_section(self, tmp_path: Path) -> None:
        """Report contains loaded handlers section."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "## Loaded Handlers" in content

    def test_contains_environment(self, tmp_path: Path) -> None:
        """Report contains environment variables section."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "## Environment" in content

    def test_contains_bug_description_section(self, tmp_path: Path) -> None:
        """Report contains bug description section."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file), description="widgets broken")

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "## Bug Description" in content
        assert "widgets broken" in content

    def test_contains_health_summary(self, tmp_path: Path) -> None:
        """Report contains health summary checklist."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        cmd_bug_report(args)

        content = output_file.read_text()
        assert "## Health Summary" in content


class TestBugReportOutput:
    """Tests for output path handling."""

    def test_output_to_specified_file(self, tmp_path: Path) -> None:
        """--output writes report to specified file."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "my-report.md"
        args = _make_args(project, output=str(output_file))

        result = cmd_bug_report(args)

        assert result == 0
        assert output_file.exists()

    def test_output_to_stdout(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """--output - prints report to stdout."""
        project = _make_project(tmp_path)
        args = _make_args(project, output="-")

        result = cmd_bug_report(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "# Bug Report" in captured.out

    def test_default_output_path(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Default output creates file in bug-reports directory."""
        project = _make_project(tmp_path)
        args = _make_args(project, output=None)

        result = cmd_bug_report(args)

        assert result == 0
        # Check that the report path was printed
        captured = capsys.readouterr()
        assert "bug-report-" in captured.out
        assert ".md" in captured.out

    def test_default_output_creates_directory(self, tmp_path: Path) -> None:
        """Default output creates bug-reports subdirectory if needed."""
        project = _make_project(tmp_path)
        args = _make_args(project, output=None)

        cmd_bug_report(args)

        bug_reports_dir = project / ".claude" / "hooks-daemon" / "untracked" / "bug-reports"
        assert bug_reports_dir.is_dir()

    def test_output_parent_directory_created(self, tmp_path: Path) -> None:
        """Output file parent directories are created if they don't exist."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "subdir" / "deep" / "report.md"
        args = _make_args(project, output=str(output_file))

        result = cmd_bug_report(args)

        assert result == 0
        assert output_file.exists()


class TestBugReportMissingConfig:
    """Tests for graceful handling of missing config."""

    def test_missing_config_still_generates(self, tmp_path: Path) -> None:
        """Report generates even when config file is missing."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        hooks_daemon_dir = claude_dir / "hooks-daemon"
        hooks_daemon_dir.mkdir()
        untracked_dir = hooks_daemon_dir / "untracked"
        untracked_dir.mkdir()

        # Create minimal config so get_project_path works
        config_file = claude_dir / "hooks-daemon.yaml"
        config_file.write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")

        output_file = tmp_path / "report.md"
        args = _make_args(tmp_path, output=str(output_file))

        result = cmd_bug_report(args)

        assert result == 0
        assert output_file.exists()


class TestTheReportIsScrubbed:
    """The report is assembled to be SHARED, so it must not carry the client.

    `BUG_REPORTING.md` sends a reporter to a PUBLIC issue tracker, and a public
    issue cannot be retracted by editing or deleting it. Before this, the report
    carried the project's `hooks-daemon.yaml` verbatim, the hostname and 100 log
    lines, and `utils/secret_redaction` — whose own threat model names a bug
    report as the thing it protects — was called by no reporting path at all.
    """

    def test_the_project_root_is_not_written_into_the_report(self, tmp_path: Path) -> None:
        """An absolute project path names the client and often the user."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"

        cmd_bug_report(_make_args(project, output=str(output_file)))

        assert str(project) not in output_file.read_text()

    def test_the_placeholder_is_present_so_paths_stay_readable(self, tmp_path: Path) -> None:
        """Scrubbing must leave a legible report, not a hole where a path was."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"

        cmd_bug_report(_make_args(project, output=str(output_file)))

        assert PROJECT_ROOT_PLACEHOLDER in output_file.read_text()

    def test_the_hostname_is_not_written_into_the_report(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """In a corporate estate a hostname routinely names the client."""
        monkeypatch.setenv("HOSTNAME", "acme-build-runner-07")
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"

        cmd_bug_report(_make_args(project, output=str(output_file)))

        assert "acme-build-runner-07" not in output_file.read_text()

    def test_a_declared_secret_term_is_redacted(self, tmp_path: Path, monkeypatch: Any) -> None:
        """The config is copied verbatim, so a term inside it reaches the report."""
        project = _make_project(tmp_path)
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '1.0'\ndaemon:\n  log_level: INFO\n  note: Voldemort\n"
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.cli.get_active_secret_terms",
            lambda: ("Voldemort",),
        )
        output_file = tmp_path / "report.md"

        cmd_bug_report(_make_args(project, output=str(output_file)))

        assert "Voldemort" not in output_file.read_text()

    def test_stdout_is_scrubbed_too(self, tmp_path: Path, capsys: Any) -> None:
        """`--output -` is the route most likely to be pasted straight into an issue."""
        project = _make_project(tmp_path)

        cmd_bug_report(_make_args(project, output="-"))

        assert str(project) not in capsys.readouterr().out

    def test_the_description_the_reporter_typed_survives(self, tmp_path: Path) -> None:
        """Over-scrubbing has a cost too: a report nobody can read is no report."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"

        cmd_bug_report(_make_args(project, output=str(output_file), description="daemon hung"))

        assert "daemon hung" in output_file.read_text()


class TestBugReportWithDaemon:
    """Tests for bug-report when daemon IS running."""

    def test_includes_daemon_info_when_running(self, tmp_path: Path) -> None:
        """Report includes extra daemon info when daemon is running."""
        project = _make_project(tmp_path)
        output_file = tmp_path / "report.md"
        args = _make_args(project, output=str(output_file))

        # Mock daemon as running with health/handler/log responses
        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.read_pid_file",
                return_value=12345,
            ),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                side_effect=_mock_daemon_responses,
            ),
        ):
            result = cmd_bug_report(args)

        assert result == 0
        content = output_file.read_text()
        assert "RUNNING" in content
        assert "12345" in content


class TestTheLogWindowIsNarrowed:
    """Plan 00403 Task 1.5: what the log capture emits, not how hard it is scrubbed.

    Scrubbing rewrites the project root, `$HOME`, the git remote and the
    hostname. It cannot reach what the daemon logged INSIDE a payload — and
    running the scrubbed command against this repository showed whole
    `hook_input` dumps in the window: the verbatim Bash command, `session_name`
    (free text a user wrote), `session_id`, `prompt_id`, `tool_use_id`.

    A 100-line window holds whatever the user was doing in the seconds before
    they asked for a report, so what it contains is not predictable and cannot
    be reasoned about after the fact. The daemon is asked for less instead.
    """

    @staticmethod
    def _captured_log_request(tmp_path: Path) -> dict[str, Any]:
        project = _make_project(tmp_path)
        args = _make_args(project, output=str(tmp_path / "report.md"))
        seen: list[dict[str, Any]] = []

        def _record(socket_path: Path, request: dict[str, Any]) -> dict[str, Any]:
            if request.get("hook_input", {}).get("action") == "get_logs":
                seen.append(request)
            return _mock_daemon_responses(socket_path, request)

        with (
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=12345),
            patch(
                "claude_code_hooks_daemon.daemon.cli.send_daemon_request",
                side_effect=_record,
            ),
        ):
            assert cmd_bug_report(args) == 0

        assert seen, "the report must actually ask the daemon for logs"
        return seen[0]

    def test_the_report_asks_for_arguments_to_be_elided(self, tmp_path: Path) -> None:
        request = self._captured_log_request(tmp_path)

        assert request["hook_input"]["elide_arguments"] is True

    def test_the_window_is_still_bounded(self, tmp_path: Path) -> None:
        """Eliding arguments is not a licence to widen the capture."""
        request = self._captured_log_request(tmp_path)

        assert request["hook_input"]["count"] == _BUG_REPORT_LOG_LINES


def _mock_daemon_responses(socket_path: Path, request: dict[str, Any]) -> dict[str, Any]:
    """Mock daemon responses for different request types."""
    action = request.get("hook_input", {}).get("action", "")

    if action == "health":
        return {
            "result": {
                "status": "healthy",
                "stats": {
                    "uptime_seconds": 120.5,
                    "requests_processed": 42,
                    "avg_processing_time_ms": 1.5,
                    "errors": 0,
                },
                "handlers": {
                    "PreToolUse": 10,
                    "PostToolUse": 5,
                    "SessionStart": 2,
                },
            }
        }
    elif action == "handlers":
        return {
            "result": {
                "handlers": {
                    "PreToolUse": [
                        {"name": "destructive-git", "priority": 10, "terminal": True},
                    ],
                }
            }
        }
    elif action == "get_logs":
        return {
            "result": {
                "logs": ["2025-01-27 INFO: Daemon started", "2025-01-27 WARNING: Test warning"],
                "count": 2,
            }
        }

    return {"result": {}}
