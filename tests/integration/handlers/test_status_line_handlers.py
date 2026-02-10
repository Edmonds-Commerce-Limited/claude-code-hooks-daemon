"""Integration tests for StatusLine handlers.

Tests: GitRepoNameHandler, AccountDisplayHandler, ModelContextHandler,
       GitBranchHandler, DaemonStatsHandler
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import make_status_line_input


# ---------------------------------------------------------------------------
# GitRepoNameHandler
# ---------------------------------------------------------------------------
class TestGitRepoNameHandler:
    """Integration tests for GitRepoNameHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.status_line.git_repo_name import (
            GitRepoNameHandler,
        )

        return GitRepoNameHandler()

    def test_matches_all_status_events(self, handler: Any) -> None:
        hook_input = make_status_line_input()
        assert handler.matches(hook_input) is True

    def test_returns_repo_name_in_context(self, handler: Any) -> None:
        hook_input = make_status_line_input()
        result = handler.handle(hook_input)
        assert result.context is not None
        assert len(result.context) > 0
        # Context should contain repo name (with emoji prefix or brackets)
        assert "test-repo" in result.context[0]

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False


# ---------------------------------------------------------------------------
# AccountDisplayHandler
# ---------------------------------------------------------------------------
class TestAccountDisplayHandler:
    """Integration tests for AccountDisplayHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.status_line.account_display import (
            AccountDisplayHandler,
        )

        return AccountDisplayHandler()

    def test_matches_all_status_events(self, handler: Any) -> None:
        hook_input = make_status_line_input()
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow(self, handler: Any) -> None:
        hook_input = make_status_line_input()
        result = handler.handle(hook_input)
        # Should always allow (context/status handler)
        assert result.decision is None or result.decision == Decision.ALLOW

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False


# ---------------------------------------------------------------------------
# ModelContextHandler
# ---------------------------------------------------------------------------
class TestModelContextHandler:
    """Integration tests for ModelContextHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.status_line.model_context import (
            ModelContextHandler,
        )

        return ModelContextHandler()

    def test_matches_all_status_events(self, handler: Any) -> None:
        hook_input = make_status_line_input()
        assert handler.matches(hook_input) is True

    @pytest.mark.parametrize(
        ("model_name", "expected_fragment"),
        [
            ("Claude Haiku 4.5", "Haiku"),
            ("Claude Sonnet 4.5", "Sonnet"),
            ("Claude Opus 4.6", "Opus"),
        ],
        ids=["haiku", "sonnet", "opus"],
    )
    def test_formats_model_name(
        self, handler: Any, model_name: str, expected_fragment: str
    ) -> None:
        hook_input = make_status_line_input(model_display_name=model_name)
        result = handler.handle(hook_input)
        assert result.context is not None
        assert len(result.context) > 0
        assert expected_fragment in result.context[0]

    @pytest.mark.parametrize(
        "used_percentage",
        [10.0, 50.0, 75.0, 95.0],
        ids=["low", "moderate", "high", "critical"],
    )
    def test_formats_context_percentage(self, handler: Any, used_percentage: float) -> None:
        hook_input = make_status_line_input(used_percentage=used_percentage)
        result = handler.handle(hook_input)
        assert result.context is not None
        assert len(result.context) > 0
        # Should contain percentage value
        assert f"{used_percentage:.1f}%" in result.context[0]

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False


# ---------------------------------------------------------------------------
# GitBranchHandler
# ---------------------------------------------------------------------------
class TestGitBranchHandler:
    """Integration tests for GitBranchHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.status_line.git_branch import (
            GitBranchHandler,
        )

        return GitBranchHandler()

    def test_matches_all_status_events(self, handler: Any) -> None:
        hook_input = make_status_line_input()
        assert handler.matches(hook_input) is True

    def test_returns_branch_for_git_repo(self, handler: Any, tmp_path: Any) -> None:
        # Use the actual workspace which is a git repo
        hook_input = make_status_line_input(cwd="/workspace")
        result = handler.handle(hook_input)
        # In a git repo, should return branch in context
        assert result.context is not None

    def test_handles_non_existent_directory(self, handler: Any) -> None:
        hook_input = make_status_line_input(cwd="/nonexistent/directory")
        result = handler.handle(hook_input)
        # Should return empty context, not error
        assert result.context is not None

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False


# ---------------------------------------------------------------------------
# DaemonStatsHandler
# ---------------------------------------------------------------------------
class TestDaemonStatsHandler:
    """Integration tests for DaemonStatsHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.status_line.daemon_stats import (
            DaemonStatsHandler,
        )

        return DaemonStatsHandler()

    def test_matches_all_status_events(self, handler: Any) -> None:
        hook_input = make_status_line_input()
        assert handler.matches(hook_input) is True

    def test_handle_returns_context(self, handler: Any) -> None:
        hook_input = make_status_line_input()
        result = handler.handle(hook_input)
        assert result.context is not None

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False
