"""Tests for LspNoiseStrategyRegistry."""

from __future__ import annotations

from claude_code_hooks_daemon.strategies.lsp_noise.registry import LspNoiseStrategyRegistry


class TestCreateDefault:
    def test_registers_every_language(self) -> None:
        registry = LspNoiseStrategyRegistry.create_default()
        assert set(registry.language_names) == {
            "Python",
            "TypeScript/JavaScript",
            "Go",
            "Rust",
            "PHP",
        }

    def test_strategies_property_exposes_every_registered_strategy(self) -> None:
        registry = LspNoiseStrategyRegistry.create_default()
        assert len(registry.strategies) == 5


class TestRegister:
    def test_register_adds_a_strategy(self) -> None:
        registry = LspNoiseStrategyRegistry()

        class _Fake:
            @property
            def language_name(self) -> str:
                return "Fake"

            @property
            def process_names(self) -> tuple[str, ...]:
                return ("fake-langserver",)

            def is_relevant(self, context: object) -> bool:
                return False

            def exclude_finding(self, root: object, required: object) -> tuple[list[str], None]:
                return [], None

            def get_acceptance_tests(self) -> list[object]:
                return []

        registry.register(_Fake())
        assert registry.language_names == ["Fake"]
