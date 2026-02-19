"""Tests for PipeBlockerStrategy Protocol conformance."""

from typing import Any

from claude_code_hooks_daemon.strategies.pipe_blocker.protocol import PipeBlockerStrategy


class MinimalConformingStrategy:
    """Minimal implementation that satisfies the Protocol."""

    @property
    def language_name(self) -> str:
        return "TestLang"

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return (r"^test_cmd\b",)

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestPipeBlockerStrategyProtocol:
    """Tests for PipeBlockerStrategy Protocol definition."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """Protocol should be checkable at runtime via isinstance."""
        strategy = MinimalConformingStrategy()
        assert isinstance(strategy, PipeBlockerStrategy)

    def test_conforming_class_passes_isinstance(self) -> None:
        """A class satisfying the Protocol should pass isinstance check."""
        strategy = MinimalConformingStrategy()
        assert isinstance(strategy, PipeBlockerStrategy)

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class missing required methods should fail isinstance check."""

        class Missing:
            pass

        assert not isinstance(Missing(), PipeBlockerStrategy)

    def test_class_missing_language_name_fails(self) -> None:
        """Class missing language_name property fails Protocol check."""

        class MissingLangName:
            @property
            def blacklist_patterns(self) -> tuple[str, ...]:
                return ()

            def get_acceptance_tests(self) -> list[Any]:
                return []

        assert not isinstance(MissingLangName(), PipeBlockerStrategy)

    def test_class_missing_blacklist_patterns_fails(self) -> None:
        """Class missing blacklist_patterns property fails Protocol check."""

        class MissingBlacklist:
            @property
            def language_name(self) -> str:
                return "X"

            def get_acceptance_tests(self) -> list[Any]:
                return []

        assert not isinstance(MissingBlacklist(), PipeBlockerStrategy)

    def test_class_missing_get_acceptance_tests_fails(self) -> None:
        """Class missing get_acceptance_tests method fails Protocol check."""

        class MissingTests:
            @property
            def language_name(self) -> str:
                return "X"

            @property
            def blacklist_patterns(self) -> tuple[str, ...]:
                return ()

        assert not isinstance(MissingTests(), PipeBlockerStrategy)

    def test_minimal_strategy_language_name(self) -> None:
        """Protocol-conforming strategy should expose language_name."""
        strategy = MinimalConformingStrategy()
        assert strategy.language_name == "TestLang"

    def test_minimal_strategy_blacklist_patterns(self) -> None:
        """Protocol-conforming strategy should expose blacklist_patterns as tuple."""
        strategy = MinimalConformingStrategy()
        assert isinstance(strategy.blacklist_patterns, tuple)

    def test_minimal_strategy_get_acceptance_tests(self) -> None:
        """Protocol-conforming strategy should return list from get_acceptance_tests."""
        strategy = MinimalConformingStrategy()
        result = strategy.get_acceptance_tests()
        assert isinstance(result, list)
