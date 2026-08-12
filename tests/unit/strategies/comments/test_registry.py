"""Tests for CommentStrategyRegistry."""

from claude_code_hooks_daemon.strategies.comments.registry import (
    CommentStrategyRegistry,
)


def test_register_and_get_strategy() -> None:
    class TestStrategy:
        @property
        def language_name(self) -> str:
            return "TestLang"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".test",)

        @property
        def syntax(self) -> object:
            return object()

        @property
        def skip_directories(self) -> tuple[str, ...]:
            return ("vendor/",)

        def get_acceptance_tests(self) -> list:
            return []

    registry = CommentStrategyRegistry()
    strategy = TestStrategy()
    registry.register(strategy)

    assert registry.get_strategy("/workspace/src/file.test") is strategy


def test_get_strategy_returns_none_for_unknown_extension() -> None:
    registry = CommentStrategyRegistry()
    assert registry.get_strategy("/workspace/src/unknown.xyz") is None


def test_get_strategy_case_insensitive() -> None:
    registry = CommentStrategyRegistry.create_default()
    assert registry.get_strategy("/workspace/src/file.PY") is not None
    assert registry.get_strategy("/workspace/src/file.Py") is not None


def test_filter_by_languages_removes_unlisted() -> None:
    registry = CommentStrategyRegistry.create_default()
    registry.filter_by_languages(["Python", "Go"])
    languages = registry.registered_languages
    assert "Python" in languages
    assert "Go" in languages
    assert len(languages) == 2


def test_filter_by_languages_empty_list_keeps_all() -> None:
    registry = CommentStrategyRegistry.create_default()
    original_count = len(registry.registered_languages)
    registry.filter_by_languages([])
    assert len(registry.registered_languages) == original_count


def test_create_default_creates_registry_with_all_languages() -> None:
    registry = CommentStrategyRegistry.create_default()
    languages = registry.registered_languages
    assert "Python" in languages
    assert "Shell" in languages
    assert "Ruby" in languages
    assert "JavaScript/TypeScript" in languages
    assert "Go" in languages
    assert "PHP" in languages
    assert "Java" in languages
    assert "Kotlin" in languages
    assert "C#" in languages
    assert "Rust" in languages
    assert "Swift" in languages
    assert "Dart" in languages
    assert len(languages) == 12


def test_create_default_resolves_python_files() -> None:
    registry = CommentStrategyRegistry.create_default()
    strategy = registry.get_strategy("/workspace/src/module.py")
    assert strategy is not None
    assert strategy.language_name == "Python"


def test_create_default_resolves_shell_files() -> None:
    registry = CommentStrategyRegistry.create_default()
    for ext in (".sh", ".bash"):
        strategy = registry.get_strategy(f"/workspace/scripts/run{ext}")
        assert strategy is not None
        assert strategy.language_name == "Shell"


def test_create_default_resolves_javascript_typescript_files() -> None:
    registry = CommentStrategyRegistry.create_default()
    for ext in (".js", ".jsx", ".ts", ".tsx"):
        strategy = registry.get_strategy(f"/workspace/src/file{ext}")
        assert strategy is not None
        assert strategy.language_name == "JavaScript/TypeScript"


def test_all_strategies_returns_deduplicated_instances() -> None:
    registry = CommentStrategyRegistry.create_default()
    strategies = registry.all_strategies
    assert len(strategies) == 12
    names = {strategy.language_name for strategy in strategies}
    assert "JavaScript/TypeScript" in names
    # JS/TS registers 4 extensions but must appear only once.
    js_count = sum(1 for s in strategies if s.language_name == "JavaScript/TypeScript")
    assert js_count == 1


def test_create_default_resolves_all_remaining_languages() -> None:
    registry = CommentStrategyRegistry.create_default()
    expectations = {
        "/workspace/src/user_service.rb": "Ruby",
        "/workspace/src/server.go": "Go",
        "/workspace/src/User.php": "PHP",
        "/workspace/src/User.java": "Java",
        "/workspace/src/User.kt": "Kotlin",
        "/workspace/src/User.cs": "C#",
        "/workspace/src/parser.rs": "Rust",
        "/workspace/src/Parser.swift": "Swift",
        "/workspace/src/parser.dart": "Dart",
    }
    for path, expected_language in expectations.items():
        strategy = registry.get_strategy(path)
        assert strategy is not None
        assert strategy.language_name == expected_language
