"""Tests for Lint Strategy Registry."""

from typing import Any

import pytest

from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry


class _MockLintStrategy:
    """Mock lint strategy for registry testing."""

    def __init__(
        self,
        language_name: str = "MockLang",
        extensions: tuple[str, ...] = (".mock",),
        default_lint_command: str = "mocklint {file}",
        extended_lint_command: str | None = None,
        skip_paths: tuple[str, ...] = ("vendor/",),
    ) -> None:
        self._language_name = language_name
        self._extensions = extensions
        self._default_lint_command = default_lint_command
        self._extended_lint_command = extended_lint_command
        self._skip_paths = skip_paths

    @property
    def language_name(self) -> str:
        return self._language_name

    @property
    def extensions(self) -> tuple[str, ...]:
        return self._extensions

    @property
    def default_lint_command(self) -> str:
        return self._default_lint_command

    @property
    def extended_lint_command(self) -> str | None:
        return self._extended_lint_command

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return self._skip_paths

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestRegistry:
    @pytest.fixture()
    def registry(self) -> LintStrategyRegistry:
        return LintStrategyRegistry()

    def test_empty_registry(self, registry: LintStrategyRegistry) -> None:
        assert registry.registered_languages == []

    def test_register_strategy(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy()
        registry.register(strategy)
        assert registry.registered_languages == ["MockLang"]

    def test_get_strategy_by_extension(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy()
        registry.register(strategy)
        result = registry.get_strategy("/workspace/src/file.mock")
        assert result is not None
        assert result.language_name == "MockLang"

    def test_get_strategy_unknown_extension(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy()
        registry.register(strategy)
        result = registry.get_strategy("/workspace/src/file.unknown")
        assert result is None

    def test_get_strategy_case_insensitive(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy()
        registry.register(strategy)
        result = registry.get_strategy("/workspace/src/file.MOCK")
        assert result is not None

    def test_register_multiple_extensions(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy(extensions=(".sh", ".bash"))
        registry.register(strategy)
        assert registry.get_strategy("/workspace/script.sh") is not None
        assert registry.get_strategy("/workspace/script.bash") is not None

    def test_register_multiple_strategies(self, registry: LintStrategyRegistry) -> None:
        strategy1 = _MockLintStrategy(language_name="Lang1", extensions=(".l1",))
        strategy2 = _MockLintStrategy(language_name="Lang2", extensions=(".l2",))
        registry.register(strategy1)
        registry.register(strategy2)
        assert set(registry.registered_languages) == {"Lang1", "Lang2"}


class TestFilterByLanguages:
    @pytest.fixture()
    def registry(self) -> LintStrategyRegistry:
        reg = LintStrategyRegistry()
        reg.register(_MockLintStrategy(language_name="Python", extensions=(".py",)))
        reg.register(_MockLintStrategy(language_name="Shell", extensions=(".sh", ".bash")))
        reg.register(_MockLintStrategy(language_name="Go", extensions=(".go",)))
        return reg

    def test_filter_keeps_matching(self, registry: LintStrategyRegistry) -> None:
        registry.filter_by_languages(["Python", "Shell"])
        assert set(registry.registered_languages) == {"Python", "Shell"}

    def test_filter_removes_non_matching(self, registry: LintStrategyRegistry) -> None:
        registry.filter_by_languages(["Python"])
        assert registry.get_strategy("/workspace/file.go") is None

    def test_filter_case_insensitive(self, registry: LintStrategyRegistry) -> None:
        registry.filter_by_languages(["python", "shell"])
        assert set(registry.registered_languages) == {"Python", "Shell"}

    def test_filter_empty_list_keeps_all(self, registry: LintStrategyRegistry) -> None:
        registry.filter_by_languages([])
        assert len(registry.registered_languages) == 3

    def test_filter_removes_all_extensions_of_language(
        self, registry: LintStrategyRegistry
    ) -> None:
        registry.filter_by_languages(["Python"])
        assert registry.get_strategy("/workspace/script.sh") is None
        assert registry.get_strategy("/workspace/script.bash") is None


class TestCreateDefault:
    def test_create_default_returns_registry(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert isinstance(registry, LintStrategyRegistry)

    def test_create_default_registers_all_languages(self) -> None:
        registry = LintStrategyRegistry.create_default()
        expected_languages = {
            "Shell",
            "Python",
            "Go",
            "Rust",
            "Ruby",
            "PHP",
            "Dart",
            "Kotlin",
            "Swift",
        }
        assert set(registry.registered_languages) == expected_languages

    def test_create_default_shell_extension(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert registry.get_strategy("/workspace/script.sh") is not None
        assert registry.get_strategy("/workspace/script.bash") is not None

    def test_create_default_python_extension(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert registry.get_strategy("/workspace/app.py") is not None

    def test_create_default_go_extension(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert registry.get_strategy("/workspace/main.go") is not None

    def test_create_default_rust_extension(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert registry.get_strategy("/workspace/lib.rs") is not None
