"""Tests for RubyPipeBlockerStrategy."""

import re

import pytest

from claude_code_hooks_daemon.strategies.pipe_blocker.ruby_strategy import RubyPipeBlockerStrategy


@pytest.fixture
def strategy() -> RubyPipeBlockerStrategy:
    return RubyPipeBlockerStrategy()


class TestRubyStrategyProperties:
    def test_language_name(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert strategy.language_name == "Ruby"

    def test_blacklist_patterns_is_tuple(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_blacklist_patterns_non_empty(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert len(strategy.blacklist_patterns) > 0


class TestRubyStrategyBlacklistPatterns:
    def test_contains_rspec(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert r"^rspec\b" in strategy.blacklist_patterns

    def test_contains_rubocop(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert r"^rubocop\b" in strategy.blacklist_patterns

    def test_contains_rake(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert r"^rake\b" in strategy.blacklist_patterns

    def test_contains_bundle_exec(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert r"^bundle\s+exec\b" in strategy.blacklist_patterns

    def test_rspec_matches(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert re.search(r"^rspec\b", "rspec spec/", re.IGNORECASE)

    def test_rubocop_matches(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert re.search(r"^rubocop\b", "rubocop app/", re.IGNORECASE)

    def test_rake_matches(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert re.search(r"^rake\b", "rake test", re.IGNORECASE)

    def test_bundle_exec_matches(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert re.search(r"^bundle\s+exec\b", "bundle exec rspec", re.IGNORECASE)

    def test_all_patterns_valid_regex(self, strategy: RubyPipeBlockerStrategy) -> None:
        for pattern in strategy.blacklist_patterns:
            re.compile(pattern, re.IGNORECASE)


class TestRubyStrategyAcceptanceTests:
    def test_returns_list(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert isinstance(strategy.get_acceptance_tests(), list)

    def test_returns_non_empty(self, strategy: RubyPipeBlockerStrategy) -> None:
        assert len(strategy.get_acceptance_tests()) > 0
