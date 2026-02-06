"""Integration tests for user interaction handlers.

Tests: AutoApproveReadsHandler (PermissionRequest),
       GitContextInjectorHandler (UserPromptSubmit),
       NotificationLoggerHandler (Notification)
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import (
    make_notification_input,
    make_permission_request_input,
    make_user_prompt_submit_input,
)


# ---------------------------------------------------------------------------
# AutoApproveReadsHandler
# ---------------------------------------------------------------------------
class TestAutoApproveReadsHandler:
    """Integration tests for AutoApproveReadsHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.permission_request.auto_approve_reads import (
            AutoApproveReadsHandler,
        )

        return AutoApproveReadsHandler()

    def test_approves_file_read(self, handler: Any) -> None:
        hook_input = make_permission_request_input("file_read", resource="/workspace/src/main.py")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_denies_file_write(self, handler: Any) -> None:
        hook_input = make_permission_request_input("file_write", resource="/workspace/src/main.py")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_ignores_other_permission_types(self, handler: Any) -> None:
        hook_input = make_permission_request_input("network_access", resource="https://example.com")
        assert handler.matches(hook_input) is False

    def test_ignores_empty_permission_type(self, handler: Any) -> None:
        hook_input = make_permission_request_input("")
        assert handler.matches(hook_input) is False


# ---------------------------------------------------------------------------
# GitContextInjectorHandler
# ---------------------------------------------------------------------------
class TestGitContextInjectorHandler:
    """Integration tests for GitContextInjectorHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.git_context_injector import (
            GitContextInjectorHandler,
        )

        return GitContextInjectorHandler()

    def test_matches_user_prompt(self, handler: Any) -> None:
        hook_input = make_user_prompt_submit_input("Please fix the bug in main.py")
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow(self, handler: Any) -> None:
        hook_input = make_user_prompt_submit_input("Show me the git status")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False


# ---------------------------------------------------------------------------
# NotificationLoggerHandler
# ---------------------------------------------------------------------------
class TestNotificationLoggerHandler:
    """Integration tests for NotificationLoggerHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.notification.notification_logger import (
            NotificationLoggerHandler,
        )

        return NotificationLoggerHandler()

    def test_matches_all_notifications(self, handler: Any) -> None:
        hook_input = make_notification_input(title="Build Complete", message="All tests passed")
        assert handler.matches(hook_input) is True

    def test_handle_returns_allow(self, handler: Any) -> None:
        hook_input = make_notification_input(title="Warning", message="Disk space low")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handler_is_non_terminal(self, handler: Any) -> None:
        assert handler.terminal is False

    def test_matches_empty_notification(self, handler: Any) -> None:
        hook_input = make_notification_input()
        assert handler.matches(hook_input) is True
