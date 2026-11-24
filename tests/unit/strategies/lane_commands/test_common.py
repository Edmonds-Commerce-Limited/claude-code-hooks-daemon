"""Tests for the lane_commands shared helpers."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core import AcceptanceTest, Decision
from claude_code_hooks_daemon.core import TestType as AcceptanceTestType
from claude_code_hooks_daemon.strategies.lane_commands.common import (
    lane_acceptance_test,
    runs_any,
)

_PATTERNS = (r"^pytest\b",)


class TestRunsAny:
    """Patterns are judged against the PEELED program, as bash would run it."""

    @pytest.mark.parametrize(
        "command",
        [
            "pytest",
            "python3 -m pytest -x",
            "uv run pytest",
            "env CI=1 pytest",
            "sudo pytest",
            "timeout 20 pytest",
            "nice -n 19 pytest",
            "sh -c 'pytest tests/'",
            "pytest &",
            "echo start; pytest",
        ],
    )
    def test_reads_through_the_common_wrappers(self, command: str) -> None:
        assert runs_any(command, _PATTERNS) is True

    @pytest.mark.parametrize(
        "command",
        ["echo pytest", "grep pytest f", "git commit -m pytest", "command -v pytest", ""],
    )
    def test_text_handed_over_as_data_is_not_a_run(self, command: str) -> None:
        assert runs_any(command, _PATTERNS) is False

    def test_no_patterns_is_never_a_run(self) -> None:
        assert runs_any("pytest", ()) is False


class TestLaneAcceptanceTest:
    def test_is_a_harness_undrivable_deny_naming_the_rule(self) -> None:
        test = lane_acceptance_test("Python", "pytest tests/unit")
        assert isinstance(test, AcceptanceTest)
        assert test.command == "pytest tests/unit"
        assert test.expected_decision == Decision.DENY
        assert test.test_type == AcceptanceTestType.BLOCKING
        assert test.harness_cannot_produce
        assert r"R-HOST-SEAT-LANE" in test.expected_message_patterns
        assert "Python" in test.title
