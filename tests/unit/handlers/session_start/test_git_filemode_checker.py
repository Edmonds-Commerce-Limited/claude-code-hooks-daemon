"""Tests for git filemode checker handler.

Detects core.fileMode=false on SessionStart and warns about hook permission issues.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision


def _session_start_input(transcript_path: str | None = None) -> dict[str, Any]:
    """Create a SessionStart hook input."""
    hook_input: dict[str, Any] = {
        HookInputField.HOOK_EVENT_NAME: "SessionStart",
    }
    if transcript_path is not None:
        hook_input[HookInputField.TRANSCRIPT_PATH] = transcript_path
    return hook_input


class TestGitFilemodeCheckerInit:
    """Test handler initialisation."""

    def test_handler_id(self) -> None:
        """Handler ID config key is git_filemode_checker."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        assert handler.handler_id.config_key == "git_filemode_checker"

    def test_non_terminal(self) -> None:
        """Handler is non-terminal (advisory)."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        assert handler.terminal is False

    def test_priority(self) -> None:
        """Handler runs at priority 53."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        assert handler.priority == 53

    def test_tags_advisory(self) -> None:
        """Handler has ADVISORY tag."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        assert HandlerTag.ADVISORY in handler.tags

    def test_tags_git(self) -> None:
        """Handler has GIT tag."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        assert HandlerTag.GIT in handler.tags

    def test_tags_non_terminal(self) -> None:
        """Handler has NON_TERMINAL tag."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        assert HandlerTag.NON_TERMINAL in handler.tags

    def test_tags_environment(self) -> None:
        """Handler has ENVIRONMENT tag."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        assert HandlerTag.ENVIRONMENT in handler.tags


class TestGitFilemodeCheckerMatches:
    """Test matches() - should only match new sessions."""

    @pytest.fixture()
    def handler(self) -> Any:
        """Create handler instance."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        return GitFilemodeCheckerHandler()

    def test_matches_new_session_no_transcript(self, handler: Any) -> None:
        """Matches when no transcript path provided (new session)."""
        assert handler.matches(_session_start_input()) is True

    def test_matches_new_session_empty_transcript(self, handler: Any) -> None:
        """Matches when transcript file is empty (new session)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            pass
        assert handler.matches(_session_start_input(tmp.name)) is True
        Path(tmp.name).unlink(missing_ok=True)

    def test_no_match_resume_session(self, handler: Any) -> None:
        """Does not match when transcript has substantial content (resume)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
            tmp.write("x" * 200)
        assert handler.matches(_session_start_input(tmp.name)) is False
        Path(tmp.name).unlink(missing_ok=True)

    def test_matches_nonexistent_transcript(self, handler: Any) -> None:
        """Matches when transcript path does not exist (new session)."""
        assert handler.matches(_session_start_input("/nonexistent/path.jsonl")) is True


class TestGitFilemodeCheckerHandle:
    """Test handle() - warning behaviour."""

    @pytest.fixture()
    def handler(self) -> Any:
        """Create handler instance."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        return GitFilemodeCheckerHandler()

    def _mock_git_result(self, stdout: str, returncode: int = 0) -> MagicMock:
        """Create a mock subprocess result."""
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stdout = stdout
        return mock_result

    def test_filemode_false_warns(self, handler: Any) -> None:
        """When core.fileMode=false, handler returns warning context."""
        with (
            patch(
                "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker.ProjectContext.project_root",
                return_value=Path("/fake/project"),
            ),
            patch("subprocess.run", return_value=self._mock_git_result("false\n")),
        ):
            result = handler.handle(_session_start_input())
        assert result.decision == Decision.ALLOW
        context_str = "\n".join(result.context)
        assert "core.fileMode" in context_str
        assert "WARNING" in context_str

    def test_filemode_false_recommends_enabling(self, handler: Any) -> None:
        """Warning includes recommendation to enable core.fileMode."""
        with (
            patch(
                "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker.ProjectContext.project_root",
                return_value=Path("/fake/project"),
            ),
            patch("subprocess.run", return_value=self._mock_git_result("false\n")),
        ):
            result = handler.handle(_session_start_input())
        context_str = "\n".join(result.context)
        assert "git config core.fileMode true" in context_str

    def test_filemode_false_warns_about_hooks(self, handler: Any) -> None:
        """Warning explains hooks may lose executable permissions."""
        with (
            patch(
                "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker.ProjectContext.project_root",
                return_value=Path("/fake/project"),
            ),
            patch("subprocess.run", return_value=self._mock_git_result("false\n")),
        ):
            result = handler.handle(_session_start_input())
        context_str = "\n".join(result.context).lower()
        assert "hook" in context_str
        assert "executable" in context_str

    def test_filemode_true_no_warning(self, handler: Any) -> None:
        """When core.fileMode=true, handler returns OK context without warning."""
        with (
            patch(
                "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker.ProjectContext.project_root",
                return_value=Path("/fake/project"),
            ),
            patch("subprocess.run", return_value=self._mock_git_result("true\n")),
        ):
            result = handler.handle(_session_start_input())
        assert result.decision == Decision.ALLOW
        context_str = "\n".join(result.context)
        assert "WARNING" not in context_str
        assert "OK" in context_str

    def test_not_git_repo_no_error(self, handler: Any) -> None:
        """When not in a git repo, handler handles gracefully."""
        with (
            patch(
                "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker.ProjectContext.project_root",
                return_value=Path("/fake/project"),
            ),
            patch("subprocess.run", return_value=self._mock_git_result("", returncode=1)),
        ):
            result = handler.handle(_session_start_input())
        assert result.decision == Decision.ALLOW

    def test_subprocess_timeout_handled(self, handler: Any) -> None:
        """When git command times out, handler handles gracefully."""
        with (
            patch(
                "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker.ProjectContext.project_root",
                return_value=Path("/fake/project"),
            ),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)),
        ):
            result = handler.handle(_session_start_input())
        assert result.decision == Decision.ALLOW

    def test_subprocess_oserror_handled(self, handler: Any) -> None:
        """When git binary not found, handler handles gracefully."""
        with (
            patch(
                "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker.ProjectContext.project_root",
                return_value=Path("/fake/project"),
            ),
            patch("subprocess.run", side_effect=OSError("No such file")),
        ):
            result = handler.handle(_session_start_input())
        assert result.decision == Decision.ALLOW

    def test_filemode_not_set_returns_ok(self, handler: Any) -> None:
        """When core.fileMode is not explicitly set, returns OK."""
        with (
            patch(
                "claude_code_hooks_daemon.handlers.session_start.git_filemode_checker.ProjectContext.project_root",
                return_value=Path("/fake/project"),
            ),
            patch("subprocess.run", return_value=self._mock_git_result("", returncode=1)),
        ):
            result = handler.handle(_session_start_input())
        assert result.decision == Decision.ALLOW
        # Should not contain a WARNING about fileMode=false
        context_str = "\n".join(result.context)
        assert "WARNING" not in context_str


class TestGitFilemodeCheckerAcceptanceTests:
    """Test get_acceptance_tests() returns valid tests."""

    def test_has_acceptance_tests(self) -> None:
        """Handler provides at least one acceptance test."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1

    def test_acceptance_test_has_title(self) -> None:
        """Acceptance test has a title."""
        from claude_code_hooks_daemon.handlers.session_start.git_filemode_checker import (
            GitFilemodeCheckerHandler,
        )

        handler = GitFilemodeCheckerHandler()
        tests = handler.get_acceptance_tests()
        assert tests[0].title
