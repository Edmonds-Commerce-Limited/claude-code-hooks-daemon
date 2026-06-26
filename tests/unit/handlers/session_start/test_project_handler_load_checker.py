"""Unit tests for ProjectHandlerLoadCheckerHandler (Plan 00143).

The handler reads the persisted project-handler health state and injects a
loud, recurring "PROJECT PROTECTION DEGRADED" alert at session start whenever
one or more project handlers failed to load — and stays silent otherwise.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.daemon.project_handler_health import (
    ProjectHandlerHealthState,
)
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoadFailure
from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
    ProjectHandlerLoadCheckerHandler,
)

_READ = "claude_code_hooks_daemon.daemon.project_handler_health.read_load_failures"


def _degraded() -> ProjectHandlerHealthState:
    return ProjectHandlerHealthState(
        failures=[
            ProjectHandlerLoadFailure(
                filename="branch_naming_enforcer.py",
                event_dir="session_start",
                reason="missing required method get_claude_md (introduced in v2.30.0)",
            ),
            ProjectHandlerLoadFailure(
                filename="phpcs_reminder.py",
                event_dir="post_tool_use",
                reason="missing required method get_claude_md (introduced in v2.30.0)",
            ),
        ],
        loaded_count=1,
    )


def _healthy() -> ProjectHandlerHealthState:
    return ProjectHandlerHealthState(failures=[], loaded_count=8)


class TestInit:
    def test_handler_identity(self) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        assert handler.name == "project-handler-load-checker"
        assert handler.priority == 50
        assert handler.terminal is False
        assert HandlerTag.ADVISORY in handler.tags


class TestMatches:
    def test_matches_when_degraded(self) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        with patch(_READ, return_value=_degraded()):
            assert handler.matches({}) is True

    def test_does_not_match_when_healthy(self) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        with patch(_READ, return_value=_healthy()):
            assert handler.matches({}) is False


class TestHandle:
    def test_loud_alert_when_degraded(self) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        with patch(_READ, return_value=_degraded()):
            result = handler.handle({})

        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        # Loud, unmissable banner.
        assert "PROJECT PROTECTION DEGRADED" in text
        # Names the count, each failed handler, its event dir, and its reason.
        assert "2" in text
        assert "branch_naming_enforcer.py" in text
        assert "session_start" in text
        assert "phpcs_reminder.py" in text
        assert "get_claude_md" in text
        # Tells the agent exactly how to remediate.
        assert "restart" in text.lower()

    def test_silent_when_healthy(self) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        with patch(_READ, return_value=_healthy()):
            result = handler.handle({})

        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestGetClaudeMd:
    def test_returns_guidance(self) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        md = handler.get_claude_md()
        assert md is not None
        assert "project_handler_load_checker" in md
        assert "restart" in md.lower()


class TestGetAcceptanceTests:
    def test_returns_at_least_one_test(self) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        tests: list[Any] = handler.get_acceptance_tests()
        assert len(tests) >= 1
