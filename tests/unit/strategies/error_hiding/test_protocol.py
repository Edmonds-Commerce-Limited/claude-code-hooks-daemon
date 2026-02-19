"""Tests for ErrorHidingPattern dataclass and ErrorHidingStrategy Protocol."""

import dataclasses

from claude_code_hooks_daemon.strategies.error_hiding.protocol import (
    ErrorHidingPattern,
    ErrorHidingStrategy,
)


class TestErrorHidingPattern:
    def test_name_stored(self) -> None:
        p = ErrorHidingPattern(
            name="|| true",
            regex=r"\|\|\s*true\b",
            example="cmd || true",
            suggestion="Handle failure explicitly",
        )
        assert p.name == "|| true"

    def test_regex_stored(self) -> None:
        p = ErrorHidingPattern(
            name="|| true",
            regex=r"\|\|\s*true\b",
            example="cmd || true",
            suggestion="Handle failure explicitly",
        )
        assert p.regex == r"\|\|\s*true\b"

    def test_example_stored(self) -> None:
        p = ErrorHidingPattern(
            name="|| true",
            regex=r"\|\|\s*true\b",
            example="cmd || true",
            suggestion="Handle failure explicitly",
        )
        assert p.example == "cmd || true"

    def test_suggestion_stored(self) -> None:
        p = ErrorHidingPattern(
            name="|| true",
            regex=r"\|\|\s*true\b",
            example="cmd || true",
            suggestion="Handle failure explicitly",
        )
        assert p.suggestion == "Handle failure explicitly"

    def test_is_frozen_dataclass(self) -> None:
        """ErrorHidingPattern must be a frozen dataclass (immutable)."""
        assert dataclasses.is_dataclass(ErrorHidingPattern)
        # Verify the dataclass has the frozen flag set
        params = getattr(ErrorHidingPattern, "__dataclass_params__", None)
        assert params is not None, "ErrorHidingPattern must be a dataclass"
        assert params.frozen is True, "ErrorHidingPattern must be frozen"

    def test_equality(self) -> None:
        p1 = ErrorHidingPattern(name="a", regex="b", example="c", suggestion="d")
        p2 = ErrorHidingPattern(name="a", regex="b", example="c", suggestion="d")
        assert p1 == p2

    def test_inequality(self) -> None:
        p1 = ErrorHidingPattern(name="a", regex="b", example="c", suggestion="d")
        p2 = ErrorHidingPattern(name="x", regex="b", example="c", suggestion="d")
        assert p1 != p2

    def test_is_hashable(self) -> None:
        """Frozen dataclasses must be hashable (usable in sets/dicts)."""
        p = ErrorHidingPattern(name="a", regex="b", example="c", suggestion="d")
        assert hash(p) is not None
        s = {p}
        assert len(s) == 1


class TestErrorHidingStrategyProtocol:
    def test_concrete_class_satisfies_protocol(self) -> None:
        """A class implementing the required attributes satisfies the protocol."""

        class ConcreteStrategy:
            @property
            def language_name(self) -> str:
                return "Test"

            @property
            def extensions(self) -> tuple[str, ...]:
                return (".test",)

            @property
            def patterns(self) -> tuple[ErrorHidingPattern, ...]:
                return ()

            def get_acceptance_tests(self) -> list:
                return []

        assert isinstance(ConcreteStrategy(), ErrorHidingStrategy)

    def test_class_missing_language_name_fails_protocol(self) -> None:
        """A class missing language_name does not satisfy the protocol."""

        class Incomplete:
            @property
            def extensions(self) -> tuple[str, ...]:
                return (".test",)

            @property
            def patterns(self) -> tuple[ErrorHidingPattern, ...]:
                return ()

            def get_acceptance_tests(self) -> list:
                return []

        assert not isinstance(Incomplete(), ErrorHidingStrategy)

    def test_class_missing_extensions_fails_protocol(self) -> None:
        """A class missing extensions does not satisfy the protocol."""

        class Incomplete:
            @property
            def language_name(self) -> str:
                return "Test"

            @property
            def patterns(self) -> tuple[ErrorHidingPattern, ...]:
                return ()

            def get_acceptance_tests(self) -> list:
                return []

        assert not isinstance(Incomplete(), ErrorHidingStrategy)

    def test_class_missing_patterns_fails_protocol(self) -> None:
        """A class missing patterns does not satisfy the protocol."""

        class Incomplete:
            @property
            def language_name(self) -> str:
                return "Test"

            @property
            def extensions(self) -> tuple[str, ...]:
                return (".test",)

            def get_acceptance_tests(self) -> list:
                return []

        assert not isinstance(Incomplete(), ErrorHidingStrategy)
