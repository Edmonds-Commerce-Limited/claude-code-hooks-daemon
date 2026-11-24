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

# The lane keeps its own per-language copy of the shared classifier's test, build
# and QA groups (utils/long_running_command.py). These pins hold the two together.

#: The one shared build pattern the lane does not take whole: it mixes languages, so
#: its names are split across the Universal, JavaScript and Java strategies instead.
_MIXED_SHARED_BUILD_PATTERN = r"^(?:tsc|webpack|gradle|gradlew|mvn|ant|cmake|ninja|bazel)\b"
_SHARED_BUILD_IN_LANE = (
    r"^(?:npm|yarn|pnpm|bun)\s+(?:build|run\s+build\S*)\b",
    r"^uv\s+build\b",
    r"^cargo\s+(?:build|check|clippy)\b",
    r"^go\s+(?:build|vet)\b",
)
_SHARED_IN_LANE = (*TEST_PATTERNS, *_SHARED_BUILD_IN_LANE, *QA_PATTERNS)

#: Lane patterns the shared classifier does not hold: the split mixed pattern, the
#: linters, and the per-language gaps. A new strategy pattern is added here too.
_LANE_ONLY_PATTERNS = (
    r"^make(?:\s+-\S+)*\s*$",
    r"^make(?:\s+-\S+)*\s+(?:test|tests|check|lint|build|qa|all|ci)\b",
    r"^(?:cmake|ninja|bazel)\b",
    r"^(?:hadolint|markdownlint|yamllint)\b",
    r"^pre-commit\s+run(?=\s|$)",
    r"^(?![\w.-]*(?:deploy|smoke|health|publish|connection))(?:[\w.-]*[_.-])?"
    r"(?:tests?|qa|lint|typecheck|type_check)(?:[_.-][\w.-]*)?\.(?:sh|bash|py)\b",
    r"^(?:ruff|mypy|pyright|pylint|flake8|black|isort|bandit)\b",
    r"^unittest\b",
    r"^(?:npm|pnpm)\s+t(?=\s|$)",
    r"^(?:tsc|webpack)\b",
    r"^(?:eslint|prettier|stylelint)\b",
    r"^(?:npm|yarn|pnpm|bun)\s+(?:run\s+)?(?:llm:)?(?:lint|typecheck|type-check|qa)\S*",
    r"^npx\s+(?:jest|vitest|playwright|mocha|tsc|eslint|prettier)\b",
    r"^shellcheck\b",
    r"^golangci-lint\b",
    r"^cargo\s+fmt\b",
    r"^ant\b",
    r"^(?:gradle|gradlew|mvn)(?!(?:.*\s)?(?:deploy|publish)(?:\s|$))\b",
    r"^rubocop\b",
    r"^(?:bundle\s+exec\s+)?rspec(?=\s|$)",
    r"^(?:phpstan|psalm|phpcs)\b",
    r"^phpunit(?=\s|$)",
    r"^composer\s+(?:test|run(?:-script)?\s+test\S*)(?=\s|$)",
    r"^dotnet\s+(?:test|build)(?=\s|$)",
)


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

    def test_the_mixed_build_pattern_is_the_only_shared_one_left_out(self) -> None:
        """A reorder or an addition to BUILD_PATTERNS cannot slip past the pin unseen."""
        assert set(BUILD_PATTERNS) == {_MIXED_SHARED_BUILD_PATTERN, *_SHARED_BUILD_IN_LANE}

    @pytest.mark.parametrize("pattern", _SHARED_IN_LANE)
    def test_the_shared_groups_the_guard_took_are_still_in_the_lane(self, pattern: str) -> None:
        """Every single-language shared test/build/QA pattern moved byte-identical."""
        assert pattern in LaneCommandStrategyRegistry.create_default().get_lane_patterns()

    def test_every_lane_pattern_is_shared_or_declared_lane_only(self) -> None:
        """The other direction: a pattern added to a strategy is listed here on purpose."""
        patterns = LaneCommandStrategyRegistry.create_default().get_lane_patterns()
        assert set(patterns) == {*_SHARED_IN_LANE, *_LANE_ONLY_PATTERNS}


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
