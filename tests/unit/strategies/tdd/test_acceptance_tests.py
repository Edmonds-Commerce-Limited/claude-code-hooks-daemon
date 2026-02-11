"""Tests for TDD strategy acceptance tests.

Verifies that all strategies provide valid acceptance tests and that
the TddEnforcementHandler aggregates them correctly.
"""

import pytest

from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType
from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import (
    TddEnforcementHandler,
)
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry
from claude_code_hooks_daemon.strategies.tdd.csharp_strategy import CSharpTddStrategy
from claude_code_hooks_daemon.strategies.tdd.dart_strategy import DartTddStrategy
from claude_code_hooks_daemon.strategies.tdd.go_strategy import GoTddStrategy
from claude_code_hooks_daemon.strategies.tdd.java_strategy import JavaTddStrategy
from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import (
    JavaScriptTddStrategy,
)
from claude_code_hooks_daemon.strategies.tdd.kotlin_strategy import KotlinTddStrategy
from claude_code_hooks_daemon.strategies.tdd.php_strategy import PhpTddStrategy
from claude_code_hooks_daemon.strategies.tdd.python_strategy import PythonTddStrategy
from claude_code_hooks_daemon.strategies.tdd.ruby_strategy import RubyTddStrategy
from claude_code_hooks_daemon.strategies.tdd.rust_strategy import RustTddStrategy
from claude_code_hooks_daemon.strategies.tdd.swift_strategy import SwiftTddStrategy

# All 11 strategy classes
ALL_STRATEGIES = [
    PythonTddStrategy,
    GoTddStrategy,
    JavaScriptTddStrategy,
    PhpTddStrategy,
    RustTddStrategy,
    JavaTddStrategy,
    CSharpTddStrategy,
    KotlinTddStrategy,
    RubyTddStrategy,
    SwiftTddStrategy,
    DartTddStrategy,
]


@pytest.mark.parametrize("strategy_class", ALL_STRATEGIES)
class TestStrategyAcceptanceTests:
    """Test acceptance tests for each strategy."""

    def test_has_get_acceptance_tests_method(self, strategy_class: type) -> None:
        """Strategy has get_acceptance_tests method."""
        strategy = strategy_class()
        assert hasattr(strategy, "get_acceptance_tests")
        assert callable(strategy.get_acceptance_tests)

    def test_returns_non_empty_list(self, strategy_class: type) -> None:
        """Strategy returns at least one acceptance test."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0, f"{strategy_class.__name__} returned empty test list"

    def test_all_items_are_acceptance_tests(self, strategy_class: type) -> None:
        """All returned items are AcceptanceTest instances."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        for test in tests:
            assert isinstance(
                test, AcceptanceTest
            ), f"{strategy_class.__name__} returned non-AcceptanceTest: {type(test)}"

    def test_expected_decision_is_deny(self, strategy_class: type) -> None:
        """All tests have expected_decision=Decision.DENY (blocking behavior)."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        for test in tests:
            assert (
                test.expected_decision == Decision.DENY
            ), f"{strategy_class.__name__} test has wrong decision: {test.expected_decision}"

    def test_has_expected_message_patterns(self, strategy_class: type) -> None:
        """All tests have non-empty expected_message_patterns."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        for test in tests:
            assert (
                test.expected_message_patterns
            ), f"{strategy_class.__name__} test has empty message patterns"
            assert isinstance(test.expected_message_patterns, list)
            assert all(isinstance(pattern, str) for pattern in test.expected_message_patterns)

    def test_includes_language_name_in_patterns(self, strategy_class: type) -> None:
        """Test patterns include the language name."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        language_name = strategy.language_name

        for test in tests:
            patterns = test.expected_message_patterns
            # Check if language name appears in any pattern
            language_in_patterns = any(
                language_name in pattern or language_name.lower() in pattern.lower()
                for pattern in patterns
            )
            assert language_in_patterns, (
                f"{strategy_class.__name__} test patterns don't include "
                f"language name '{language_name}': {patterns}"
            )

    def test_test_type_is_blocking(self, strategy_class: type) -> None:
        """All tests have test_type=TestType.BLOCKING."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        for test in tests:
            assert (
                test.test_type == TestType.BLOCKING
            ), f"{strategy_class.__name__} test has wrong type: {test.test_type}"

    def test_has_setup_commands(self, strategy_class: type) -> None:
        """All tests have setup_commands for directory creation."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        for test in tests:
            assert test.setup_commands, f"{strategy_class.__name__} test missing setup_commands"
            assert isinstance(test.setup_commands, list)
            assert len(test.setup_commands) > 0

    def test_has_cleanup_commands(self, strategy_class: type) -> None:
        """All tests have cleanup_commands for removal."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        for test in tests:
            assert test.cleanup_commands, f"{strategy_class.__name__} test missing cleanup_commands"
            assert isinstance(test.cleanup_commands, list)
            assert len(test.cleanup_commands) > 0

    def test_uses_tmp_path(self, strategy_class: type) -> None:
        """All tests use /tmp path for safety."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        for test in tests:
            assert (
                "/tmp/" in test.command
            ), f"{strategy_class.__name__} test doesn't use /tmp path: {test.command}"

    def test_has_safety_notes(self, strategy_class: type) -> None:
        """All tests have safety_notes explaining why they're safe."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        for test in tests:
            assert test.safety_notes, f"{strategy_class.__name__} test missing safety_notes"
            assert isinstance(test.safety_notes, str)
            assert len(test.safety_notes) > 0


class TestTddEnforcementHandlerAggregation:
    """Test that TddEnforcementHandler aggregates all strategy tests."""

    @pytest.fixture
    def handler(self) -> TddEnforcementHandler:
        """Create handler with default registry."""
        return TddEnforcementHandler()

    def test_handler_aggregates_all_strategies(self, handler: TddEnforcementHandler) -> None:
        """Handler aggregates acceptance tests from all 11 strategies."""
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        # Should have at least 11 tests (one per strategy)
        assert len(tests) >= 11, f"Expected at least 11 tests, got {len(tests)}"

    def test_all_aggregated_tests_are_acceptance_tests(
        self, handler: TddEnforcementHandler
    ) -> None:
        """All aggregated tests are AcceptanceTest instances."""
        tests = handler.get_acceptance_tests()
        for test in tests:
            assert isinstance(test, AcceptanceTest)

    def test_aggregation_includes_all_languages(self, handler: TddEnforcementHandler) -> None:
        """Aggregated tests include all 11 language strategies."""
        tests = handler.get_acceptance_tests()

        # Expected language names in test patterns
        expected_languages = [
            "Python",
            "Go",
            "JavaScript/TypeScript",
            "PHP",
            "Rust",
            "Java",
            "C#",
            "Kotlin",
            "Ruby",
            "Swift",
            "Dart",
        ]

        found_languages: set[str] = set()
        for test in tests:
            for language in expected_languages:
                if any(
                    language in pattern or language.lower() in pattern.lower()
                    for pattern in test.expected_message_patterns
                ):
                    found_languages.add(language)

        assert len(found_languages) == len(
            expected_languages
        ), f"Missing languages: {set(expected_languages) - found_languages}"

    def test_no_duplicate_languages(self, handler: TddEnforcementHandler) -> None:
        """Handler doesn't duplicate tests for the same language."""
        tests = handler.get_acceptance_tests()

        # Count language occurrences using exact pattern match
        # (avoids "Java" substring-matching "JavaScript/TypeScript")
        registry = TddStrategyRegistry.create_default()
        all_language_names = registry.registered_languages

        language_test_counts: dict[str, int] = {}
        for test in tests:
            for language in all_language_names:
                # Exact match only - pattern must equal the language name exactly
                if any(pattern == language for pattern in test.expected_message_patterns):
                    language_test_counts[language] = language_test_counts.get(language, 0) + 1

        # Each found language should appear exactly once
        for language, count in language_test_counts.items():
            assert count == 1, f"Language '{language}' appears {count} times (expected 1)"

    def test_aggregation_with_custom_registry(self) -> None:
        """Handler aggregates tests from custom registry."""
        # Create a registry with only Python strategy
        registry = TddStrategyRegistry()
        registry.register(PythonTddStrategy())

        handler = TddEnforcementHandler()
        handler._registry = registry

        tests = handler.get_acceptance_tests()
        assert len(tests) == 1  # Only Python test
        assert any(
            "Python" in pattern for test in tests for pattern in test.expected_message_patterns
        )


class TestAcceptanceTestValidation:
    """Test that all acceptance tests pass validation."""

    def test_all_tests_pass_dataclass_validation(self) -> None:
        """All strategy acceptance tests pass AcceptanceTest validation."""
        for strategy_class in ALL_STRATEGIES:
            strategy = strategy_class()
            tests = strategy.get_acceptance_tests()
            for test in tests:
                # If we got here without raising ValueError, validation passed
                assert test.title
                assert test.command
                assert test.description
