"""Tests for the LspNoiseStrategy Protocol."""

import importlib
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.strategies.lsp_noise.protocol import LspNoiseStrategy


def test_protocol_is_runtime_checkable() -> None:
    """LspNoiseStrategy Protocol should be runtime checkable."""
    assert getattr(LspNoiseStrategy, "_is_runtime_protocol", False) is True


def test_protocol_has_expected_members() -> None:
    """Protocol should define all expected members."""
    protocol_attrs = set(dir(LspNoiseStrategy))

    assert "language_name" in protocol_attrs
    assert "process_names" in protocol_attrs
    assert "is_relevant" in protocol_attrs
    assert "exclude_finding" in protocol_attrs
    assert "get_acceptance_tests" in protocol_attrs


def test_complete_implementation_satisfies_protocol() -> None:
    """A class implementing every member satisfies the isinstance check."""

    class CompleteLspNoiseStrategy:
        @property
        def language_name(self) -> str:
            return "TestLang"

        @property
        def process_names(self) -> tuple[str, ...]:
            return ("test-langserver",)

        def is_relevant(self, context: Any) -> bool:
            return False

        def exclude_finding(
            self, root: Path, required: frozenset[str]
        ) -> tuple[list[str], Path | None]:
            return [], None

        def get_acceptance_tests(self) -> list[Any]:
            return []

    strategy = CompleteLspNoiseStrategy()
    assert isinstance(strategy, LspNoiseStrategy)


def test_incomplete_implementation_does_not_satisfy_protocol() -> None:
    """A class missing members does NOT satisfy the isinstance check."""

    class IncompleteLspNoiseStrategy:
        @property
        def language_name(self) -> str:
            return "TestLang"

        # Missing: process_names, is_relevant, exclude_finding, get_acceptance_tests

    strategy = IncompleteLspNoiseStrategy()
    assert not isinstance(strategy, LspNoiseStrategy)


class TestRealImplementationsSatisfyProtocol:
    """Every real strategy implementation must satisfy the protocol."""

    @pytest.mark.parametrize(
        "strategy_class",
        [
            "PythonLspNoiseStrategy",
            "TypeScriptLspNoiseStrategy",
            "GoLspNoiseStrategy",
            "RustLspNoiseStrategy",
            "PhpLspNoiseStrategy",
        ],
    )
    def test_strategy_satisfies_protocol(self, strategy_class: str) -> None:
        module_name = strategy_class.replace("LspNoiseStrategy", "").lower()
        module_path = f"claude_code_hooks_daemon.strategies.lsp_noise.{module_name}_strategy"

        module = importlib.import_module(module_path)
        strategy_cls = getattr(module, strategy_class)

        strategy = strategy_cls()
        assert isinstance(
            strategy, LspNoiseStrategy
        ), f"{strategy_class} should satisfy LspNoiseStrategy protocol"
