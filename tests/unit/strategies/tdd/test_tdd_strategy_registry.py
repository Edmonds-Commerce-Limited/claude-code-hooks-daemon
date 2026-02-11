"""Tests for TDD Strategy Registry."""

from claude_code_hooks_daemon.strategies.tdd.registry import TddStrategyRegistry


def test_register_and_get_strategy() -> None:
    """Should register a strategy and retrieve it by extension."""

    class TestStrategy:
        """Test strategy for registration."""

        @property
        def language_name(self) -> str:
            return "TestLang"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".test",)

        def is_test_file(self, file_path: str) -> bool:
            return True

        def is_production_source(self, file_path: str) -> bool:
            return True

        def should_skip(self, file_path: str) -> bool:
            return False

        def compute_test_filename(self, source_filename: str) -> str:
            return f"test_{source_filename}"

    registry = TddStrategyRegistry()
    strategy = TestStrategy()
    registry.register(strategy)

    retrieved = registry.get_strategy("/workspace/src/file.test")
    assert retrieved is strategy


def test_get_strategy_returns_none_for_unknown_extension() -> None:
    """Should return None for unknown file extensions."""
    registry = TddStrategyRegistry()
    assert registry.get_strategy("/workspace/src/unknown.xyz") is None


def test_get_strategy_case_insensitive() -> None:
    """Should match extensions case-insensitively."""

    class TestStrategy:
        """Test strategy for case insensitivity."""

        @property
        def language_name(self) -> str:
            return "TestLang"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".test",)

        def is_test_file(self, file_path: str) -> bool:
            return True

        def is_production_source(self, file_path: str) -> bool:
            return True

        def should_skip(self, file_path: str) -> bool:
            return False

        def compute_test_filename(self, source_filename: str) -> str:
            return f"test_{source_filename}"

    registry = TddStrategyRegistry()
    strategy = TestStrategy()
    registry.register(strategy)

    assert registry.get_strategy("/workspace/src/file.TEST") is strategy
    assert registry.get_strategy("/workspace/src/file.Test") is strategy


def test_register_multiple_extensions() -> None:
    """Should register a strategy for all its declared extensions."""

    class MultiExtStrategy:
        """Test strategy with multiple extensions."""

        @property
        def language_name(self) -> str:
            return "MultiExt"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".js", ".jsx", ".ts", ".tsx")

        def is_test_file(self, file_path: str) -> bool:
            return True

        def is_production_source(self, file_path: str) -> bool:
            return True

        def should_skip(self, file_path: str) -> bool:
            return False

        def compute_test_filename(self, source_filename: str) -> str:
            return f"test_{source_filename}"

    registry = TddStrategyRegistry()
    strategy = MultiExtStrategy()
    registry.register(strategy)

    assert registry.get_strategy("/workspace/src/file.js") is strategy
    assert registry.get_strategy("/workspace/src/file.jsx") is strategy
    assert registry.get_strategy("/workspace/src/file.ts") is strategy
    assert registry.get_strategy("/workspace/src/file.tsx") is strategy


def test_registered_languages() -> None:
    """Should return deduplicated list of registered language names."""

    class LangA:
        """Test strategy A."""

        @property
        def language_name(self) -> str:
            return "LangA"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".a",)

        def is_test_file(self, file_path: str) -> bool:
            return True

        def is_production_source(self, file_path: str) -> bool:
            return True

        def should_skip(self, file_path: str) -> bool:
            return False

        def compute_test_filename(self, source_filename: str) -> str:
            return f"test_{source_filename}"

    class LangB:
        """Test strategy B."""

        @property
        def language_name(self) -> str:
            return "LangB"

        @property
        def extensions(self) -> tuple[str, ...]:
            return (".b1", ".b2")

        def is_test_file(self, file_path: str) -> bool:
            return True

        def is_production_source(self, file_path: str) -> bool:
            return True

        def should_skip(self, file_path: str) -> bool:
            return False

        def compute_test_filename(self, source_filename: str) -> str:
            return f"test_{source_filename}"

    registry = TddStrategyRegistry()
    registry.register(LangA())
    registry.register(LangB())

    languages = registry.registered_languages
    assert "LangA" in languages
    assert "LangB" in languages
    # LangB registered with 2 extensions but should appear only once
    assert languages.count("LangB") == 1


def test_filter_by_languages_removes_unlisted() -> None:
    """filter_by_languages should remove strategies not in the given list."""
    registry = TddStrategyRegistry.create_default()
    registry.filter_by_languages(["Python", "Go"])
    languages = registry.registered_languages
    assert "Python" in languages
    assert "Go" in languages
    assert len(languages) == 2


def test_filter_by_languages_case_insensitive() -> None:
    """filter_by_languages should match language names case-insensitively."""
    registry = TddStrategyRegistry.create_default()
    registry.filter_by_languages(["python", "go"])
    languages = registry.registered_languages
    assert "Python" in languages
    assert "Go" in languages
    assert len(languages) == 2


def test_filter_by_languages_empty_list_keeps_all() -> None:
    """filter_by_languages with empty list should keep all strategies (no filtering)."""
    registry = TddStrategyRegistry.create_default()
    original_count = len(registry.registered_languages)
    registry.filter_by_languages([])
    assert len(registry.registered_languages) == original_count


def test_filter_by_languages_removes_extensions_too() -> None:
    """filter_by_languages should remove extension mappings for filtered languages."""
    registry = TddStrategyRegistry.create_default()
    registry.filter_by_languages(["Python"])
    assert registry.get_strategy("/workspace/src/file.py") is not None
    assert registry.get_strategy("/workspace/src/file.go") is None
    assert registry.get_strategy("/workspace/src/file.js") is None


def test_filter_by_languages_with_slash_name() -> None:
    """filter_by_languages should work with compound names like 'JavaScript/TypeScript'."""
    registry = TddStrategyRegistry.create_default()
    registry.filter_by_languages(["JavaScript/TypeScript"])
    languages = registry.registered_languages
    assert "JavaScript/TypeScript" in languages
    assert len(languages) == 1
    # All JS/TS extensions should still work
    assert registry.get_strategy("/workspace/src/file.js") is not None
    assert registry.get_strategy("/workspace/src/file.tsx") is not None


def test_create_default_creates_registry_with_all_languages() -> None:
    """Should create registry with all 11 built-in language strategies."""
    registry = TddStrategyRegistry.create_default()

    languages = registry.registered_languages
    assert "Python" in languages
    assert "Go" in languages
    assert "JavaScript/TypeScript" in languages
    assert "PHP" in languages
    assert "Rust" in languages
    assert "Java" in languages
    assert "C#" in languages
    assert "Kotlin" in languages
    assert "Ruby" in languages
    assert "Swift" in languages
    assert "Dart" in languages
    assert len(languages) == 11


def test_create_default_resolves_python_files() -> None:
    """Default registry should resolve .py files to Python strategy."""
    registry = TddStrategyRegistry.create_default()
    strategy = registry.get_strategy("/workspace/src/module.py")
    assert strategy is not None
    assert strategy.language_name == "Python"


def test_create_default_resolves_go_files() -> None:
    """Default registry should resolve .go files to Go strategy."""
    registry = TddStrategyRegistry.create_default()
    strategy = registry.get_strategy("/workspace/src/server.go")
    assert strategy is not None
    assert strategy.language_name == "Go"


def test_create_default_resolves_javascript_typescript_files() -> None:
    """Default registry should resolve JS/TS files to JavaScript/TypeScript strategy."""
    registry = TddStrategyRegistry.create_default()

    for ext in [".js", ".jsx", ".ts", ".tsx"]:
        strategy = registry.get_strategy(f"/workspace/src/file{ext}")
        assert strategy is not None
        assert strategy.language_name == "JavaScript/TypeScript"


def test_create_default_resolves_php_files() -> None:
    """Default registry should resolve .php files to PHP strategy."""
    registry = TddStrategyRegistry.create_default()
    strategy = registry.get_strategy("/workspace/src/User.php")
    assert strategy is not None
    assert strategy.language_name == "PHP"


def test_create_default_resolves_rust_files() -> None:
    """Default registry should resolve .rs files to Rust strategy."""
    registry = TddStrategyRegistry.create_default()
    strategy = registry.get_strategy("/workspace/src/parser.rs")
    assert strategy is not None
    assert strategy.language_name == "Rust"


def test_create_default_resolves_java_files() -> None:
    """Default registry should resolve .java files to Java strategy."""
    registry = TddStrategyRegistry.create_default()
    strategy = registry.get_strategy("/workspace/src/User.java")
    assert strategy is not None
    assert strategy.language_name == "Java"
