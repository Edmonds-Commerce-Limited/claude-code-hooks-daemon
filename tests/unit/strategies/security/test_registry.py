"""Tests for SecurityStrategyRegistry."""

import pytest

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.strategies.security.registry import (
    SecurityStrategyRegistry,
)


class _MockUniversalStrategy:
    """Mock universal strategy for testing."""

    @property
    def language_name(self) -> str:
        return "Universal"

    @property
    def extensions(self) -> tuple[str, ...]:
        return ("*",)

    @property
    def patterns(self) -> tuple[SecurityPattern, ...]:
        return (SecurityPattern(name="Test", regex=r"test", owasp="A01", suggestion="fix"),)

    def get_acceptance_tests(self) -> list:
        return []


class _MockPhpStrategy:
    """Mock PHP strategy for testing."""

    @property
    def language_name(self) -> str:
        return "PHP"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".php",)

    @property
    def patterns(self) -> tuple[SecurityPattern, ...]:
        return (SecurityPattern(name="PHP Test", regex=r"php_test", owasp="A03", suggestion="fix"),)

    def get_acceptance_tests(self) -> list:
        return []


class _MockJsStrategy:
    """Mock JavaScript strategy for testing."""

    @property
    def language_name(self) -> str:
        return "JavaScript"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".ts", ".js")

    @property
    def patterns(self) -> tuple[SecurityPattern, ...]:
        return (SecurityPattern(name="JS Test", regex=r"js_test", owasp="A03", suggestion="fix"),)

    def get_acceptance_tests(self) -> list:
        return []


class TestSecurityStrategyRegistry:
    """Test suite for SecurityStrategyRegistry."""

    @pytest.fixture
    def registry(self):
        return SecurityStrategyRegistry()

    @pytest.fixture
    def populated_registry(self):
        reg = SecurityStrategyRegistry()
        reg.register(_MockUniversalStrategy())
        reg.register(_MockPhpStrategy())
        reg.register(_MockJsStrategy())
        return reg

    # ── Registration ──────────────────────────────────────────────────

    def test_register_universal_strategy(self, registry):
        registry.register(_MockUniversalStrategy())
        assert len(registry._universal_strategies) == 1

    def test_register_extension_strategy(self, registry):
        registry.register(_MockPhpStrategy())
        assert ".php" in registry._extension_strategies

    def test_register_multi_extension_strategy(self, registry):
        registry.register(_MockJsStrategy())
        assert ".ts" in registry._extension_strategies
        assert ".js" in registry._extension_strategies

    # ── get_strategies() ──────────────────────────────────────────────

    def test_get_strategies_returns_universal_for_any_file(self, populated_registry):
        strategies = populated_registry.get_strategies("/workspace/src/config.py")
        language_names = [s.language_name for s in strategies]
        assert "Universal" in language_names

    def test_get_strategies_returns_universal_plus_php(self, populated_registry):
        strategies = populated_registry.get_strategies("/workspace/src/app.php")
        language_names = [s.language_name for s in strategies]
        assert "Universal" in language_names
        assert "PHP" in language_names

    def test_get_strategies_returns_universal_plus_js(self, populated_registry):
        strategies = populated_registry.get_strategies("/workspace/src/app.ts")
        language_names = [s.language_name for s in strategies]
        assert "Universal" in language_names
        assert "JavaScript" in language_names

    def test_get_strategies_no_duplicate_languages(self, populated_registry):
        strategies = populated_registry.get_strategies("/workspace/src/app.ts")
        language_names = [s.language_name for s in strategies]
        assert len(language_names) == len(set(language_names))

    def test_get_strategies_empty_registry(self, registry):
        strategies = registry.get_strategies("/workspace/src/app.py")
        assert strategies == []

    # ── filter_by_languages() ─────────────────────────────────────────

    def test_filter_removes_non_matching(self, populated_registry):
        populated_registry.filter_by_languages(["PHP", "Universal"])
        strategies = populated_registry.get_strategies("/workspace/src/app.ts")
        language_names = [s.language_name for s in strategies]
        assert "JavaScript" not in language_names
        assert "Universal" in language_names

    def test_filter_case_insensitive(self, populated_registry):
        populated_registry.filter_by_languages(["php", "universal"])
        assert "PHP" in populated_registry.registered_languages

    def test_filter_empty_list_keeps_all(self, populated_registry):
        populated_registry.filter_by_languages([])
        assert len(populated_registry.registered_languages) == 3

    # ── registered_languages ──────────────────────────────────────────

    def test_registered_languages(self, populated_registry):
        languages = populated_registry.registered_languages
        assert "Universal" in languages
        assert "PHP" in languages
        assert "JavaScript" in languages

    def test_registered_languages_no_duplicates(self, populated_registry):
        languages = populated_registry.registered_languages
        assert len(languages) == len(set(languages))

    # ── all_strategies ────────────────────────────────────────────────

    def test_all_strategies(self, populated_registry):
        strategies = populated_registry.all_strategies
        assert len(strategies) == 3

    # ── create_default() ──────────────────────────────────────────────

    def test_create_default_has_secrets(self):
        registry = SecurityStrategyRegistry.create_default()
        assert "Secrets" in registry.registered_languages

    def test_create_default_has_php(self):
        registry = SecurityStrategyRegistry.create_default()
        assert "PHP" in registry.registered_languages

    def test_create_default_has_javascript(self):
        registry = SecurityStrategyRegistry.create_default()
        assert "JavaScript" in registry.registered_languages
