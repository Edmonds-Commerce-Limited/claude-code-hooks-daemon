"""Tests for Kotlin lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.common import lint_output_dir
from claude_code_hooks_daemon.strategies.lint.kotlin_strategy import KotlinLintStrategy
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy


@pytest.fixture()
def strategy() -> KotlinLintStrategy:
    return KotlinLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: KotlinLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: KotlinLintStrategy) -> None:
        assert strategy.language_name == "Kotlin"

    def test_extensions(self, strategy: KotlinLintStrategy) -> None:
        assert strategy.extensions == (".kt",)

    def test_default_lint_command(self, strategy: KotlinLintStrategy) -> None:
        assert strategy.default_lint_command == (
            f"kotlinc -nowarn -d {lint_output_dir()} {{file}}"
        )

    def test_default_lint_command_sends_output_to_the_shared_scratch_dir(
        self, strategy: KotlinLintStrategy
    ) -> None:
        """Not a fixed name in the shared temp directory (Plan 00364 Task 3.3)."""
        assert lint_output_dir() in strategy.default_lint_command

    def test_extended_lint_command(self, strategy: KotlinLintStrategy) -> None:
        assert strategy.extended_lint_command == "ktlint {file}"

    def test_skip_paths_is_tuple(self, strategy: KotlinLintStrategy) -> None:
        assert isinstance(strategy.skip_paths, tuple)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: KotlinLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: KotlinLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
