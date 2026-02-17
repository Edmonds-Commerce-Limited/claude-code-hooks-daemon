"""Tests for TDD Strategy Protocol."""

import pytest

from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


def test_protocol_is_runtime_checkable() -> None:
    """TddStrategy Protocol should be runtime checkable."""
    # Check if the protocol is decorated with @runtime_checkable
    # This is indicated by the presence of _is_runtime_protocol attribute
    assert getattr(TddStrategy, "_is_runtime_protocol", False) is True


def test_complete_implementation_satisfies_protocol() -> None:
    """A class implementing all methods should satisfy isinstance check."""

    class CompleteTddStrategy:
        """Complete implementation for testing."""

        @property
        def language_name(self) -> str:
            return "TestLang"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".test",)

        def is_test_file(self, file_path: str) -> bool:
            return file_path.endswith("_test.test")

        def is_production_source(self, file_path: str) -> bool:
            return "/src/" in file_path

        def should_skip(self, file_path: str) -> bool:
            return "/vendor/" in file_path

        def compute_test_filename(self, source_filename: str) -> str:
            return f"test_{source_filename}"

        def get_acceptance_tests(self) -> list:
            return []

    strategy = CompleteTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_incomplete_implementation_does_not_satisfy_protocol() -> None:
    """A class missing methods should NOT satisfy isinstance check."""

    class IncompleteTddStrategy:
        """Incomplete implementation missing methods."""

        @property
        def language_name(self) -> str:
            return "TestLang"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".test",)

        # Missing: is_test_file, is_production_source, should_skip, compute_test_filename

    strategy = IncompleteTddStrategy()
    assert not isinstance(strategy, TddStrategy)


def test_protocol_has_expected_methods() -> None:
    """Protocol should define all expected method signatures."""
    protocol_attrs = set(dir(TddStrategy))

    assert "language_name" in protocol_attrs
    assert "extensions" in protocol_attrs
    assert "is_test_file" in protocol_attrs
    assert "is_production_source" in protocol_attrs
    assert "should_skip" in protocol_attrs
    assert "compute_test_filename" in protocol_attrs
    assert "get_acceptance_tests" in protocol_attrs


class TestRealImplementationsSatisfyProtocol:
    """Test that all real strategy implementations satisfy the protocol."""

    @pytest.mark.parametrize(
        "strategy_class",
        [
            "PythonTddStrategy",
            "GoTddStrategy",
            "JavaScriptTddStrategy",
            "PhpTddStrategy",
            "RustTddStrategy",
            "JavaTddStrategy",
            "CSharpTddStrategy",
            "KotlinTddStrategy",
            "RubyTddStrategy",
            "SwiftTddStrategy",
            "DartTddStrategy",
        ],
    )
    def test_strategy_satisfies_protocol(self, strategy_class: str) -> None:
        """Test that each real strategy implementation satisfies TddStrategy protocol."""
        # Import the strategy class dynamically
        module_name = strategy_class.replace("TddStrategy", "").lower()
        module_path = f"claude_code_hooks_daemon.strategies.tdd.{module_name}_strategy"

        module = __import__(module_path, fromlist=[strategy_class])
        strategy_cls = getattr(module, strategy_class)

        # Instantiate and check isinstance
        strategy = strategy_cls()
        assert isinstance(
            strategy, TddStrategy
        ), f"{strategy_class} should satisfy TddStrategy protocol"
