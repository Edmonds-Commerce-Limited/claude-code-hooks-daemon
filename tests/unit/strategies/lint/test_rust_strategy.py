"""Tests for Rust lint strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.rust_strategy import RustLintStrategy


@pytest.fixture()
def strategy() -> RustLintStrategy:
    return RustLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: RustLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)


class TestProperties:
    def test_language_name(self, strategy: RustLintStrategy) -> None:
        assert strategy.language_name == "Rust"

    def test_extensions(self, strategy: RustLintStrategy) -> None:
        assert strategy.extensions == (".rs",)

    def test_default_lint_command(self, strategy: RustLintStrategy) -> None:
        assert (
            strategy.default_lint_command
            == "rustc --edition 2021 --crate-type lib -Z parse-only {file}"
        )

    def test_extended_lint_command(self, strategy: RustLintStrategy) -> None:
        assert strategy.extended_lint_command == "clippy-driver {file}"

    def test_skip_paths_contains_target(self, strategy: RustLintStrategy) -> None:
        assert any("target" in p for p in strategy.skip_paths)


class TestAcceptanceTests:
    def test_returns_list(self, strategy: RustLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: RustLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1
