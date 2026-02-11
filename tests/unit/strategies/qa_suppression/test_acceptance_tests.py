"""Tests for QA suppression strategy acceptance tests.

Verifies that all strategies provide valid acceptance tests.
"""

import pytest

from claude_code_hooks_daemon.core import AcceptanceTest, Decision, TestType
from claude_code_hooks_daemon.strategies.qa_suppression.csharp_strategy import (
    CSharpQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.dart_strategy import (
    DartQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.go_strategy import (
    GoQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.java_strategy import (
    JavaQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.javascript_strategy import (
    JavaScriptQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.kotlin_strategy import (
    KotlinQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.php_strategy import (
    PhpQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
    PythonQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.ruby_strategy import (
    RubyQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.rust_strategy import (
    RustQaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.swift_strategy import (
    SwiftQaSuppressionStrategy,
)

# All 11 strategy classes
ALL_STRATEGIES = [
    PythonQaSuppressionStrategy,
    GoQaSuppressionStrategy,
    JavaScriptQaSuppressionStrategy,
    PhpQaSuppressionStrategy,
    RustQaSuppressionStrategy,
    JavaQaSuppressionStrategy,
    CSharpQaSuppressionStrategy,
    KotlinQaSuppressionStrategy,
    RubyQaSuppressionStrategy,
    SwiftQaSuppressionStrategy,
    DartQaSuppressionStrategy,
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
            assert all(isinstance(p, str) for p in test.expected_message_patterns)

    def test_includes_language_name_in_patterns(self, strategy_class: type) -> None:
        """Test patterns include the language name."""
        strategy = strategy_class()
        tests = strategy.get_acceptance_tests()
        language_name = strategy.language_name

        for test in tests:
            patterns = test.expected_message_patterns
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


class TestAcceptanceTestValidation:
    """Test that all acceptance tests pass validation."""

    def test_all_tests_pass_dataclass_validation(self) -> None:
        """All strategy acceptance tests pass AcceptanceTest validation."""
        for strategy_class in ALL_STRATEGIES:
            strategy = strategy_class()
            tests = strategy.get_acceptance_tests()
            for test in tests:
                assert test.title
                assert test.command
                assert test.description
