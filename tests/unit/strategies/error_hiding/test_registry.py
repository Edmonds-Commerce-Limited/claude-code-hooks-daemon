"""Tests for ErrorHidingStrategyRegistry."""

import pytest

from claude_code_hooks_daemon.strategies.error_hiding.registry import (
    ErrorHidingStrategyRegistry,
)


@pytest.fixture
def registry() -> ErrorHidingStrategyRegistry:
    return ErrorHidingStrategyRegistry.create_default()


class TestErrorHidingStrategyRegistryInit:
    def test_empty_registry_returns_none_for_any_file(self) -> None:
        reg = ErrorHidingStrategyRegistry()
        assert reg.get_strategy("test.py") is None

    def test_create_default_returns_registry(self) -> None:
        reg = ErrorHidingStrategyRegistry.create_default()
        assert isinstance(reg, ErrorHidingStrategyRegistry)


class TestErrorHidingStrategyRegistryGetStrategy:
    def test_returns_shell_strategy_for_sh(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/script.sh")
        assert strategy is not None
        assert strategy.language_name == "Shell"

    def test_returns_shell_strategy_for_bash(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/script.bash")
        assert strategy is not None
        assert strategy.language_name == "Shell"

    def test_returns_python_strategy_for_py(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/module.py")
        assert strategy is not None
        assert strategy.language_name == "Python"

    def test_returns_js_strategy_for_js(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/app.js")
        assert strategy is not None
        assert strategy.language_name == "JavaScript/TypeScript"

    def test_returns_js_strategy_for_ts(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/app.ts")
        assert strategy is not None
        assert strategy.language_name == "JavaScript/TypeScript"

    def test_returns_js_strategy_for_tsx(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/Component.tsx")
        assert strategy is not None
        assert strategy.language_name == "JavaScript/TypeScript"

    def test_returns_js_strategy_for_jsx(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/Component.jsx")
        assert strategy is not None
        assert strategy.language_name == "JavaScript/TypeScript"

    def test_returns_js_strategy_for_mjs(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/module.mjs")
        assert strategy is not None
        assert strategy.language_name == "JavaScript/TypeScript"

    def test_returns_js_strategy_for_cjs(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/module.cjs")
        assert strategy is not None
        assert strategy.language_name == "JavaScript/TypeScript"

    def test_returns_go_strategy_for_go(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/main.go")
        assert strategy is not None
        assert strategy.language_name == "Go"

    def test_returns_java_strategy_for_java(self, registry: ErrorHidingStrategyRegistry) -> None:
        strategy = registry.get_strategy("/some/path/Main.java")
        assert strategy is not None
        assert strategy.language_name == "Java"

    def test_returns_none_for_unknown_extension(
        self, registry: ErrorHidingStrategyRegistry
    ) -> None:
        assert registry.get_strategy("/some/path/file.xyz") is None

    def test_returns_none_for_txt(self, registry: ErrorHidingStrategyRegistry) -> None:
        assert registry.get_strategy("/some/path/readme.txt") is None

    def test_case_insensitive_extension_matching(
        self, registry: ErrorHidingStrategyRegistry
    ) -> None:
        # Extensions are matched case-insensitively
        strategy = registry.get_strategy("/some/path/SCRIPT.SH")
        assert strategy is not None
        assert strategy.language_name == "Shell"


class TestErrorHidingStrategyRegistryFilterByLanguages:
    def test_filter_removes_non_matching_strategies(self) -> None:
        registry = ErrorHidingStrategyRegistry.create_default()
        registry.filter_by_languages(["Python"])
        # After filtering, only Python remains
        assert registry.get_strategy("test.py") is not None
        assert registry.get_strategy("test.sh") is None
        assert registry.get_strategy("test.js") is None

    def test_filter_case_insensitive(self) -> None:
        registry = ErrorHidingStrategyRegistry.create_default()
        registry.filter_by_languages(["python"])
        assert registry.get_strategy("test.py") is not None
        assert registry.get_strategy("test.sh") is None

    def test_filter_empty_list_keeps_all(self) -> None:
        registry = ErrorHidingStrategyRegistry.create_default()
        original_py = registry.get_strategy("test.py")
        original_sh = registry.get_strategy("test.sh")
        registry.filter_by_languages([])
        # Empty filter = no filtering
        assert registry.get_strategy("test.py") is original_py
        assert registry.get_strategy("test.sh") is original_sh

    def test_filter_multiple_languages(self) -> None:
        registry = ErrorHidingStrategyRegistry.create_default()
        registry.filter_by_languages(["Python", "Go"])
        assert registry.get_strategy("test.py") is not None
        assert registry.get_strategy("test.go") is not None
        assert registry.get_strategy("test.sh") is None
        assert registry.get_strategy("test.js") is None

    def test_filter_unknown_language_removes_all(self) -> None:
        registry = ErrorHidingStrategyRegistry.create_default()
        registry.filter_by_languages(["Nonexistent"])
        # No matching strategy remains
        assert registry.get_strategy("test.py") is None
        assert registry.get_strategy("test.sh") is None


class TestErrorHidingStrategyRegistryRegisteredLanguages:
    def test_default_registry_has_all_languages(
        self, registry: ErrorHidingStrategyRegistry
    ) -> None:
        languages = registry.registered_languages
        assert "Shell" in languages
        assert "Python" in languages
        assert "JavaScript/TypeScript" in languages
        assert "Go" in languages
        assert "Java" in languages

    def test_registered_languages_no_duplicates(
        self, registry: ErrorHidingStrategyRegistry
    ) -> None:
        languages = registry.registered_languages
        assert len(languages) == len(set(languages))
