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


_OPTION_FAILURES = {"PreToolUse.destructive_git": "RuntimeError: injected"}


def _with_option_failures() -> ProjectHandlerLoadCheckerHandler:
    """A checker as the registry leaves it after a pass-1 failure (Plan 00466 N19)."""
    handler = ProjectHandlerLoadCheckerHandler()
    handler._option_failures = dict(_OPTION_FAILURES)
    return handler


class TestOptionFailures:
    """``health`` is only seen when someone runs it, so session start says it too."""

    def test_matches_when_a_handler_runs_on_defaults(self) -> None:
        with patch(_READ, return_value=_healthy()):
            assert _with_option_failures().matches({}) is True

    def test_still_needed_while_a_handler_runs_on_defaults(self) -> None:
        with patch(_READ, return_value=_healthy()):
            assert _with_option_failures().verify_still_needed() is True

    def test_names_each_handler_key_and_that_it_runs_on_defaults(self) -> None:
        with patch(_READ, return_value=_healthy()):
            text = "\n".join(_with_option_failures().handle({}).context)
        assert "PreToolUse.destructive_git" in text
        assert "RuntimeError: injected" in text
        assert "defaults" in text
        # Project handlers all loaded, so their alert stays out of it.
        assert "PROJECT PROTECTION DEGRADED" not in text

    def test_both_alerts_when_both_are_degraded(self) -> None:
        with patch(_READ, return_value=_degraded()):
            text = "\n".join(_with_option_failures().handle({}).context)
        assert "PROJECT PROTECTION DEGRADED" in text
        assert "PreToolUse.destructive_git" in text

    def test_no_option_failures_by_default(self) -> None:
        with patch(_READ, return_value=_healthy()):
            assert ProjectHandlerLoadCheckerHandler().verify_still_needed() is False


_CONFIG_PROBLEM = (
    "daemon.transport.timeout_seconds=90 is too long; using 45. "
    "To fix: set it to 45 or less in .claude/hooks-daemon.yaml."
)


def _with_config_problems() -> ProjectHandlerLoadCheckerHandler:
    """A checker as the registry leaves it for a config the daemon adjusted."""
    handler = ProjectHandlerLoadCheckerHandler()
    handler._config_problems = [_CONFIG_PROBLEM]
    return handler


class TestConfigProblems:
    """Plan 00466 round 3: a config value the daemon did not apply as written
    is named at session start, not only in the daemon log."""

    def test_matches_when_a_value_is_not_in_force(self) -> None:
        with patch(_READ, return_value=_healthy()):
            assert _with_config_problems().matches({}) is True

    def test_names_the_problem_and_says_it_is_the_configs(self) -> None:
        with patch(_READ, return_value=_healthy()):
            text = "\n".join(_with_config_problems().handle({}).context)
        assert "CONFIG VALUE NOT IN FORCE" in text
        assert _CONFIG_PROBLEM in text
        assert "PROJECT PROTECTION DEGRADED" not in text
        assert "daemon defect" not in text

    def test_it_is_not_a_degraded_session(self) -> None:
        """The clamp is the safe direction: every guard is on."""
        with patch(_READ, return_value=_healthy()):
            assert _with_config_problems().verify_still_needed() is False

    def test_no_config_problems_by_default(self) -> None:
        with patch(_READ, return_value=_healthy()):
            assert ProjectHandlerLoadCheckerHandler().matches({}) is False


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
