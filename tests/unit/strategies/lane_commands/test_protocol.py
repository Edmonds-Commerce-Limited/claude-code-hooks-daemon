"""Tests for LaneCommandStrategy Protocol conformance."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.protocol import LaneCommandStrategy


class _Conforming:
    @property
    def language_name(self) -> str:
        return "TestLang"

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return (r"^test_cmd\b",)

    def get_acceptance_tests(self) -> list[Any]:
        return []


class _MissingPatterns:
    @property
    def language_name(self) -> str:
        return "TestLang"

    def get_acceptance_tests(self) -> list[Any]:
        return []


class _MissingLanguage:
    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return ()

    def get_acceptance_tests(self) -> list[Any]:
        return []


class _MissingAcceptance:
    @property
    def language_name(self) -> str:
        return "TestLang"

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return ()


class TestLaneCommandStrategyProtocol:
    def test_conforming_class_passes_isinstance(self) -> None:
        assert isinstance(_Conforming(), LaneCommandStrategy)

    def test_missing_patterns_fails(self) -> None:
        assert not isinstance(_MissingPatterns(), LaneCommandStrategy)

    def test_missing_language_name_fails(self) -> None:
        assert not isinstance(_MissingLanguage(), LaneCommandStrategy)

    def test_missing_acceptance_tests_fails(self) -> None:
        assert not isinstance(_MissingAcceptance(), LaneCommandStrategy)

    def test_members_are_readable_on_a_real_strategy(self) -> None:
        from claude_code_hooks_daemon.strategies.lane_commands.python_strategy import (
            PythonLaneCommandStrategy,
        )

        strategy: LaneCommandStrategy = PythonLaneCommandStrategy()
        assert isinstance(strategy, LaneCommandStrategy)
        assert strategy.language_name == "Python"
        assert strategy.lane_patterns
        assert strategy.get_acceptance_tests()
