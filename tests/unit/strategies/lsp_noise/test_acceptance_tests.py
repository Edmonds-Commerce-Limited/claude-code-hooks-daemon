"""Tests that every lsp_noise strategy provides valid acceptance tests, and
that LspNoiseCheckerHandler aggregates them correctly (Strategy Pattern
archetype rule: the handler is a thin aggregator, deduplicated by
language_name, adding nothing of its own)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType
from claude_code_hooks_daemon.handlers.session_start.lsp_noise_checker import (
    LspNoiseCheckerHandler,
)
from claude_code_hooks_daemon.strategies.lsp_noise.go_strategy import GoLspNoiseStrategy
from claude_code_hooks_daemon.strategies.lsp_noise.php_strategy import PhpLspNoiseStrategy
from claude_code_hooks_daemon.strategies.lsp_noise.python_strategy import (
    PythonLspNoiseStrategy,
)
from claude_code_hooks_daemon.strategies.lsp_noise.registry import LspNoiseStrategyRegistry
from claude_code_hooks_daemon.strategies.lsp_noise.rust_strategy import RustLspNoiseStrategy
from claude_code_hooks_daemon.strategies.lsp_noise.typescript_strategy import (
    TypeScriptLspNoiseStrategy,
)

ALL_STRATEGIES = [
    PythonLspNoiseStrategy,
    TypeScriptLspNoiseStrategy,
    GoLspNoiseStrategy,
    RustLspNoiseStrategy,
    PhpLspNoiseStrategy,
]


@pytest.mark.parametrize("strategy_class", ALL_STRATEGIES)
class TestStrategyAcceptanceTests:
    def test_returns_non_empty_list(self, strategy_class: type) -> None:
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0, f"{strategy_class.__name__} returned empty test list"

    def test_all_items_are_acceptance_tests(self, strategy_class: type) -> None:
        strategy = strategy_class()
        for test in strategy.get_acceptance_tests():
            assert isinstance(test, AcceptanceTest)

    def test_expected_decision_is_allow(self, strategy_class: type) -> None:
        strategy = strategy_class()
        for test in strategy.get_acceptance_tests():
            assert test.expected_decision == Decision.ALLOW

    def test_test_type_is_context(self, strategy_class: type) -> None:
        strategy = strategy_class()
        for test in strategy.get_acceptance_tests():
            assert test.test_type == TestType.CONTEXT

    def test_includes_language_name_in_patterns(self, strategy_class: type) -> None:
        """At least one '/'-separated component of language_name appears -
        a slash-joined name like 'TypeScript/JavaScript' need not appear whole."""
        strategy = strategy_class()
        language_name = strategy.language_name
        components = language_name.split("/")
        for test in strategy.get_acceptance_tests():
            joined = " ".join(test.expected_message_patterns)
            assert any(component in joined for component in components), (
                f"{strategy_class.__name__} test patterns don't include any of "
                f"{components}: {test.expected_message_patterns}"
            )

    def test_has_safety_notes(self, strategy_class: type) -> None:
        strategy = strategy_class()
        for test in strategy.get_acceptance_tests():
            assert test.safety_notes


class TestHandlerAggregation:
    @pytest.fixture
    def handler(self) -> LspNoiseCheckerHandler:
        return LspNoiseCheckerHandler()

    def test_handler_aggregates_every_strategy(self, handler: LspNoiseCheckerHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= len(ALL_STRATEGIES)

    def test_no_duplicate_languages(self, handler: LspNoiseCheckerHandler) -> None:
        registry = LspNoiseStrategyRegistry.create_default()
        tests = handler.get_acceptance_tests()

        counts: dict[str, int] = {}
        for test in tests:
            for language in registry.language_names:
                if any(language in pattern for pattern in test.expected_message_patterns):
                    counts[language] = counts.get(language, 0) + 1

        for language, count in counts.items():
            assert count == 1, f"Language {language!r} appears {count} times (expected 1)"
