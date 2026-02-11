"""Tests for QA Suppression Strategy Protocol."""

from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


def test_protocol_is_runtime_checkable() -> None:
    """QaSuppressionStrategy Protocol should be runtime checkable."""
    assert getattr(QaSuppressionStrategy, "_is_runtime_protocol", False) is True


def test_complete_implementation_satisfies_protocol() -> None:
    """A class implementing all properties/methods should satisfy isinstance check."""

    class CompleteStrategy:
        """Complete implementation for testing."""

        @property
        def language_name(self) -> str:
            return "TestLang"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".test",)

        @property
        def forbidden_patterns(self) -> tuple[str, ...]:
            return (r"pattern",)

        @property
        def skip_directories(self) -> tuple[str, ...]:
            return ("vendor/",)

        @property
        def tool_names(self) -> tuple[str, ...]:
            return ("TestTool",)

        @property
        def tool_docs_urls(self) -> tuple[str, ...]:
            return ("https://example.com/",)

        def get_acceptance_tests(self) -> list:
            return []

    strategy = CompleteStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_incomplete_implementation_does_not_satisfy_protocol() -> None:
    """A class missing properties should NOT satisfy isinstance check."""

    class IncompleteStrategy:
        """Incomplete implementation missing properties."""

        @property
        def language_name(self) -> str:
            return "TestLang"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".test",)

        # Missing: forbidden_patterns, skip_directories, tool_names,
        # tool_docs_urls, get_acceptance_tests

    strategy = IncompleteStrategy()
    assert not isinstance(strategy, QaSuppressionStrategy)


def test_protocol_has_expected_attributes() -> None:
    """Protocol should define all expected property and method signatures."""
    protocol_attrs = set(dir(QaSuppressionStrategy))

    assert "language_name" in protocol_attrs
    assert "extensions" in protocol_attrs
    assert "forbidden_patterns" in protocol_attrs
    assert "skip_directories" in protocol_attrs
    assert "tool_names" in protocol_attrs
    assert "tool_docs_urls" in protocol_attrs
    assert "get_acceptance_tests" in protocol_attrs
