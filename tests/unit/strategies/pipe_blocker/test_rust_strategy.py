"""Tests for RustPipeBlockerStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.pipe_blocker.rust_strategy import RustPipeBlockerStrategy


@pytest.fixture
def strategy() -> RustPipeBlockerStrategy:
    return RustPipeBlockerStrategy()


class TestRustStrategyProperties:
    def test_language_name(self, strategy: RustPipeBlockerStrategy) -> None:
        assert strategy.language_name == "Rust"

    def test_blacklist_patterns_is_tuple(self, strategy: RustPipeBlockerStrategy) -> None:
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_blacklist_patterns_non_empty(self, strategy: RustPipeBlockerStrategy) -> None:
        assert len(strategy.blacklist_patterns) > 0


class TestRustStrategyBlacklistPatterns:
    def test_contains_cargo_test(self, strategy: RustPipeBlockerStrategy) -> None:
        assert r"^cargo\s+test\b" in strategy.blacklist_patterns

    def test_contains_cargo_build(self, strategy: RustPipeBlockerStrategy) -> None:
        assert r"^cargo\s+build\b" in strategy.blacklist_patterns

    def test_contains_cargo_check(self, strategy: RustPipeBlockerStrategy) -> None:
        assert r"^cargo\s+check\b" in strategy.blacklist_patterns

    def test_contains_cargo_clippy(self, strategy: RustPipeBlockerStrategy) -> None:
        assert r"^cargo\s+clippy\b" in strategy.blacklist_patterns

    def test_cargo_test_matches(self, strategy: RustPipeBlockerStrategy) -> None:
        assert re.search(r"^cargo\s+test\b", "cargo test", re.IGNORECASE)

    def test_cargo_build_matches(self, strategy: RustPipeBlockerStrategy) -> None:
        assert re.search(r"^cargo\s+build\b", "cargo build --release", re.IGNORECASE)

    def test_cargo_clippy_matches(self, strategy: RustPipeBlockerStrategy) -> None:
        assert re.search(r"^cargo\s+clippy\b", "cargo clippy -- -D warnings", re.IGNORECASE)

    def test_all_patterns_valid_regex(self, strategy: RustPipeBlockerStrategy) -> None:
        for pattern in strategy.blacklist_patterns:
            re.compile(pattern, re.IGNORECASE)


class TestRustStrategyAcceptanceTests:
    def test_returns_list(self, strategy: RustPipeBlockerStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: RustPipeBlockerStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) > 0
