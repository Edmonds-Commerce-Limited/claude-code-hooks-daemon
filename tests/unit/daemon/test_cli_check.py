"""Tests for the ``cmd_check`` CLI command (Plan 00128).

``cli check`` is the on-demand verbose environment/configuration audit. It
surfaces exactly what SessionStart deliberately keeps quiet: the full Claude
Code optimal-config report (output tokens, bash working dir, etc.), container
runtime, git core.fileMode, and hook-registration drift.
"""

import argparse
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_check

_OPT_MODULE = (
    "claude_code_hooks_daemon.handlers.session_start.optimal_config_checker."
    "OptimalConfigCheckerHandler._run_checks"
)
_FILEMODE_MODULE = (
    "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker."
    "GitFilemodeCheckerHandler._get_filemode_setting"
)
_CONTAINER_MODULE = "claude_code_hooks_daemon.utils.container_detection"
_REGISTRATION = "claude_code_hooks_daemon.daemon.cli.check_hook_registration_warnings"
_HEALTH = "claude_code_hooks_daemon.daemon.cli._read_project_handler_health"


def _check(name: str, passed: bool) -> dict[str, Any]:
    """Build a single optimal-config check result dict."""
    return {
        "name": name,
        "passed": passed,
        "current": "Not set" if not passed else "set",
        "why": f"why-{name}",
        "fix": f"fix-{name}",
        "where": f"where-{name}",
        "docs": "https://code.claude.com/docs/en/settings",
    }


def _args() -> argparse.Namespace:
    return argparse.Namespace(project_root=None)


def _patches(
    *,
    checks: list[dict[str, Any]] | None = None,
    runtime: str | None = None,
    in_container: bool = False,
    filemode: str | None = "true",
    warnings: list[str] | None = None,
    health: Any = None,
) -> Any:
    """Patch every external probe cmd_check relies on, for determinism."""
    from claude_code_hooks_daemon.daemon.project_handler_health import (
        ProjectHandlerHealthState,
    )

    checks = checks if checks is not None else [_check("Agent Teams", True)]
    warnings = warnings if warnings is not None else []
    health = health if health is not None else ProjectHandlerHealthState()
    return (
        patch(_OPT_MODULE, return_value=checks),
        patch(_FILEMODE_MODULE, return_value=filemode),
        patch(f"{_CONTAINER_MODULE}.detect_container_runtime", return_value=runtime),
        patch(f"{_CONTAINER_MODULE}.in_container", return_value=in_container),
        patch(_REGISTRATION, return_value=warnings),
        patch(_HEALTH, return_value=health),
    )


class TestCmdCheck:
    def test_returns_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The audit is advisory — it never fails the shell."""
        with self._enter(_patches()):
            assert cmd_check(_args()) == 0

    def test_reports_failing_config_with_fix_and_docs(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A failing optimal-config check shows the fix + docs (the verbose
        content that moved here out of SessionStart)."""
        checks = [_check("Max Output Tokens", False)]
        with self._enter(_patches(checks=checks)):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "Max Output Tokens" in out
        assert "fix-Max Output Tokens" in out
        assert "code.claude.com" in out

    def test_reports_passing_config(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Passing checks are listed as OK."""
        checks = [_check("Agent Teams", True), _check("Effort Level", True)]
        with self._enter(_patches(checks=checks)):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "Agent Teams" in out
        assert "Effort Level" in out

    def test_reports_container_runtime(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._enter(_patches(runtime="podman", in_container=True)):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "podman" in out

    def test_reports_not_in_container(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._enter(_patches(runtime=None, in_container=False)):
            cmd_check(_args())
        out = capsys.readouterr().out.lower()
        assert "not in a container" in out

    def test_reports_filemode_true_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._enter(_patches(filemode="true")):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "fileMode" in out
        assert "OK" in out

    def test_reports_filemode_false_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._enter(_patches(filemode="false")):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "core.fileMode true" in out

    def test_reports_hook_registration_ok(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._enter(_patches(warnings=[])):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "Hook registration" in out

    def test_reports_hook_registration_issues(self, capsys: pytest.CaptureFixture[str]) -> None:
        with self._enter(_patches(warnings=["settings.local.json has a hooks entry"])):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "settings.local.json has a hooks entry" in out

    def test_reports_project_handler_degraded(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.daemon.project_handler_health import (
            ProjectHandlerHealthState,
        )
        from claude_code_hooks_daemon.handlers.project_loader import (
            ProjectHandlerLoadFailure,
        )

        degraded = ProjectHandlerHealthState(
            failures=[
                ProjectHandlerLoadFailure(
                    filename="phpcs_reminder.py",
                    event_dir="post_tool_use",
                    reason="missing get_claude_md (v2.30.0)",
                )
            ],
            loaded_count=1,
        )
        with self._enter(_patches(health=degraded)):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "DEGRADED" in out
        assert "phpcs_reminder.py" in out

    def test_reports_project_handler_ok_when_clean(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with self._enter(_patches()):
            cmd_check(_args())
        out = capsys.readouterr().out
        assert "Project handler" in out

    @staticmethod
    def _enter(patches: Any) -> Any:
        """Context manager that enters all patches together."""
        from contextlib import ExitStack

        stack = ExitStack()
        for p in patches:
            stack.enter_context(p)
        return stack
