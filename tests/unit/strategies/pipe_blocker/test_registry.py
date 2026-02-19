"""Tests for PipeBlockerStrategyRegistry."""

from typing import Any

from claude_code_hooks_daemon.strategies.pipe_blocker.registry import PipeBlockerStrategyRegistry


class _FakeStrategy:
    """Minimal strategy for testing."""

    def __init__(self, name: str, patterns: tuple[str, ...]) -> None:
        self._name = name
        self._patterns = patterns

    @property
    def language_name(self) -> str:
        return self._name

    @property
    def blacklist_patterns(self) -> tuple[str, ...]:
        return self._patterns

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestPipeBlockerStrategyRegistryInit:
    """Tests for registry initialization."""

    def test_empty_on_init(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        assert registry.registered_languages == []

    def test_registered_languages_is_list(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        assert isinstance(registry.registered_languages, list)


class TestPipeBlockerStrategyRegistryRegister:
    """Tests for register method."""

    def test_register_single_strategy(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        assert "Python" in registry.registered_languages

    def test_register_multiple_strategies(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.register(_FakeStrategy("Go", (r"^go\s+test\b",)))
        assert "Python" in registry.registered_languages
        assert "Go" in registry.registered_languages

    def test_register_replaces_existing(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.register(_FakeStrategy("Python", (r"^mypy\b",)))
        patterns = registry.get_blacklist_patterns()
        assert r"^mypy\b" in patterns
        assert r"^pytest\b" not in patterns


class TestPipeBlockerStrategyRegistryGetBlacklistPatterns:
    """Tests for get_blacklist_patterns method."""

    def test_empty_registry_returns_empty_tuple(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        assert registry.get_blacklist_patterns() == ()

    def test_single_strategy_patterns_merged(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b", r"^mypy\b")))
        patterns = registry.get_blacklist_patterns()
        assert r"^pytest\b" in patterns
        assert r"^mypy\b" in patterns

    def test_multiple_strategies_patterns_merged(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.register(_FakeStrategy("Go", (r"^go\s+test\b",)))
        patterns = registry.get_blacklist_patterns()
        assert r"^pytest\b" in patterns
        assert r"^go\s+test\b" in patterns

    def test_returns_tuple(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        assert isinstance(registry.get_blacklist_patterns(), tuple)

    def test_empty_strategy_patterns_still_works(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Empty", ()))
        assert registry.get_blacklist_patterns() == ()


class TestPipeBlockerStrategyRegistryFilterByLanguages:
    """Tests for filter_by_languages method."""

    def test_empty_filter_keeps_all(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.register(_FakeStrategy("Go", (r"^go\s+test\b",)))
        registry.filter_by_languages([])
        assert "Python" in registry.registered_languages
        assert "Go" in registry.registered_languages

    def test_filter_removes_unallowed_languages(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.register(_FakeStrategy("Go", (r"^go\s+test\b",)))
        registry.filter_by_languages(["Python"])
        assert "Python" in registry.registered_languages
        assert "Go" not in registry.registered_languages

    def test_filter_case_insensitive(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.filter_by_languages(["python"])  # lowercase
        assert "Python" in registry.registered_languages

    def test_universal_always_kept(self) -> None:
        """Universal strategy is never removed by language filter."""
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Universal", (r"^make\b",)))
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.filter_by_languages(["Python"])  # don't mention Universal
        assert "Universal" in registry.registered_languages
        assert "Python" in registry.registered_languages

    def test_universal_kept_when_only_other_language_listed(self) -> None:
        """Universal stays even when only a different language is listed."""
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Universal", (r"^make\b",)))
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.register(_FakeStrategy("Go", (r"^go\s+test\b",)))
        registry.filter_by_languages(["Go"])
        assert "Universal" in registry.registered_languages
        assert "Go" in registry.registered_languages
        assert "Python" not in registry.registered_languages

    def test_filter_removes_patterns_from_removed_strategies(self) -> None:
        registry = PipeBlockerStrategyRegistry()
        registry.register(_FakeStrategy("Python", (r"^pytest\b",)))
        registry.register(_FakeStrategy("Go", (r"^go\s+test\b",)))
        registry.filter_by_languages(["Python"])
        patterns = registry.get_blacklist_patterns()
        assert r"^pytest\b" in patterns
        assert r"^go\s+test\b" not in patterns


class TestPipeBlockerStrategyRegistryCreateDefault:
    """Tests for create_default class method."""

    def test_create_default_returns_registry(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert isinstance(registry, PipeBlockerStrategyRegistry)

    def test_create_default_has_universal(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert "Universal" in registry.registered_languages

    def test_create_default_has_python(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert "Python" in registry.registered_languages

    def test_create_default_has_javascript(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert "JavaScript" in registry.registered_languages

    def test_create_default_has_go(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert "Go" in registry.registered_languages

    def test_create_default_has_rust(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert "Rust" in registry.registered_languages

    def test_create_default_has_java(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert "Java" in registry.registered_languages

    def test_create_default_has_ruby(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert "Ruby" in registry.registered_languages

    def test_create_default_has_shell(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert "Shell" in registry.registered_languages

    def test_create_default_blacklist_non_empty(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        assert len(registry.get_blacklist_patterns()) > 0

    def test_create_default_includes_pytest_pattern(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        patterns = registry.get_blacklist_patterns()
        assert r"^pytest\b" in patterns

    def test_create_default_includes_npm_test_pattern(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        patterns = registry.get_blacklist_patterns()
        assert r"^npm\s+test\b" in patterns

    def test_create_default_includes_make_pattern(self) -> None:
        registry = PipeBlockerStrategyRegistry.create_default()
        patterns = registry.get_blacklist_patterns()
        assert r"^make\b" in patterns
