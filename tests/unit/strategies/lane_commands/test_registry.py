"""Tests for LaneCommandStrategyRegistry."""

from __future__ import annotations

import re
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.protocol import LaneCommandStrategy
from claude_code_hooks_daemon.strategies.lane_commands.registry import (
    LaneCommandStrategyRegistry,
)
from claude_code_hooks_daemon.utils.long_running_command import (
    BUILD_PATTERNS,
    QA_PATTERNS,
    TEST_PATTERNS,
)

_EXPECTED_LANGUAGES = [
    "Universal",
    "Python",
    "JavaScript",
    "Shell",
    "Go",
    "Rust",
    "Java",
    "Ruby",
    "PHP",
    ".NET",
]


class _Fake:
    def __init__(self, name: str, patterns: tuple[str, ...]) -> None:
        self._name = name
        self._patterns = patterns

    @property
    def language_name(self) -> str:
        return self._name

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return self._patterns

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestRegistry:
    def test_empty_on_init(self) -> None:
        registry = LaneCommandStrategyRegistry()
        assert registry.registered_languages == []
        assert registry.strategies() == []
        assert registry.get_lane_patterns() == ()

    def test_patterns_merge_in_registration_order(self) -> None:
        registry = LaneCommandStrategyRegistry()
        registry.register(_Fake("Python", (r"^pytest\b",)))
        registry.register(_Fake("Go", (r"^go\s+test\b",)))
        assert registry.get_lane_patterns() == (r"^pytest\b", r"^go\s+test\b")

    def test_register_replaces_by_language_name(self) -> None:
        registry = LaneCommandStrategyRegistry()
        registry.register(_Fake("Python", (r"^pytest\b",)))
        replacement = _Fake("Python", (r"^mypy\b",))
        registry.register(replacement)
        assert registry.strategies() == [replacement]
        assert registry.get_lane_patterns() == (r"^mypy\b",)


class TestDefaultRegistry:
    def test_registers_the_expected_languages(self) -> None:
        registry = LaneCommandStrategyRegistry.create_default()
        assert registry.registered_languages == _EXPECTED_LANGUAGES

    def test_every_strategy_satisfies_the_protocol(self) -> None:
        for strategy in LaneCommandStrategyRegistry.create_default().strategies():
            assert isinstance(strategy, LaneCommandStrategy)

    def test_every_pattern_compiles(self) -> None:
        for pattern in LaneCommandStrategyRegistry.create_default().get_lane_patterns():
            re.compile(pattern)

    def test_no_pattern_is_listed_twice(self) -> None:
        patterns = LaneCommandStrategyRegistry.create_default().get_lane_patterns()
        assert len(patterns) == len(set(patterns))

    @pytest.mark.parametrize("pattern", [*TEST_PATTERNS, *BUILD_PATTERNS[1:], *QA_PATTERNS])
    def test_the_shared_groups_the_guard_took_are_still_in_the_lane(self, pattern: str) -> None:
        """Every single-language shared test/build/QA pattern moved byte-identical."""
        assert pattern in LaneCommandStrategyRegistry.create_default().get_lane_patterns()


class TestAcceptanceTests:
    """Every strategy declares at least one harness-undrivable lane refusal."""

    @pytest.mark.parametrize(
        "strategy",
        LaneCommandStrategyRegistry.create_default().strategies(),
        ids=lambda strategy: strategy.language_name,
    )
    def test_each_strategy_declares_a_lane_refusal(self, strategy: LaneCommandStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert tests
        for test in tests:
            assert test.expected_decision == Decision.DENY
            assert test.harness_cannot_produce
            assert strategy.language_name in test.title
            assert runs_any(test.command, strategy.lane_patterns) is True
