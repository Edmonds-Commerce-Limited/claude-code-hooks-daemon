"""TDD Strategy Registry - maps file extensions to strategy implementations."""

from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


class TddStrategyRegistry:
    """Registry mapping file extensions to TDD strategy implementations.

    Supports:
    - Registering strategies by their declared extensions
    - Looking up strategy for a file path
    - Listing all registered strategies
    - Creating a default registry with all built-in strategies
    """

    def __init__(self) -> None:
        self._strategies: dict[str, TddStrategy] = {}

    def register(self, strategy: TddStrategy) -> None:
        """Register a strategy for all its declared extensions."""
        for ext in strategy.extensions:
            self._strategies[ext.lower()] = strategy

    def get_strategy(self, file_path: str) -> TddStrategy | None:
        """Get the strategy for a file path based on its extension."""
        file_path_lower = file_path.lower()
        for ext, strategy in self._strategies.items():
            if file_path_lower.endswith(ext):
                return strategy
        return None

    def filter_by_languages(self, language_names: list[str]) -> None:
        """Remove strategies whose language_name is not in the given list.

        Matching is case-insensitive. If language_names is empty, no filtering
        is applied (all strategies remain).
        """
        if not language_names:
            return
        allowed = {name.lower() for name in language_names}
        to_remove = [
            ext
            for ext, strategy in self._strategies.items()
            if strategy.language_name.lower() not in allowed
        ]
        for ext in to_remove:
            del self._strategies[ext]

    @property
    def registered_languages(self) -> list[str]:
        """Get names of all registered languages (deduplicated)."""
        seen: set[str] = set()
        result: list[str] = []
        for strategy in self._strategies.values():
            if strategy.language_name not in seen:
                seen.add(strategy.language_name)
                result.append(strategy.language_name)
        return result

    @classmethod
    def create_default(cls) -> "TddStrategyRegistry":
        """Create registry with ALL built-in language strategies."""
        # Lazy imports to avoid circular dependencies
        from claude_code_hooks_daemon.strategies.tdd.csharp_strategy import (
            CSharpTddStrategy,
        )
        from claude_code_hooks_daemon.strategies.tdd.dart_strategy import DartTddStrategy
        from claude_code_hooks_daemon.strategies.tdd.go_strategy import GoTddStrategy
        from claude_code_hooks_daemon.strategies.tdd.java_strategy import JavaTddStrategy
        from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import (
            JavaScriptTddStrategy,
        )
        from claude_code_hooks_daemon.strategies.tdd.kotlin_strategy import (
            KotlinTddStrategy,
        )
        from claude_code_hooks_daemon.strategies.tdd.php_strategy import PhpTddStrategy
        from claude_code_hooks_daemon.strategies.tdd.python_strategy import (
            PythonTddStrategy,
        )
        from claude_code_hooks_daemon.strategies.tdd.ruby_strategy import RubyTddStrategy
        from claude_code_hooks_daemon.strategies.tdd.rust_strategy import RustTddStrategy
        from claude_code_hooks_daemon.strategies.tdd.swift_strategy import (
            SwiftTddStrategy,
        )

        registry = cls()
        registry.register(PythonTddStrategy())
        registry.register(GoTddStrategy())
        registry.register(JavaScriptTddStrategy())
        registry.register(PhpTddStrategy())
        registry.register(RustTddStrategy())
        registry.register(JavaTddStrategy())
        registry.register(CSharpTddStrategy())
        registry.register(KotlinTddStrategy())
        registry.register(RubyTddStrategy())
        registry.register(SwiftTddStrategy())
        registry.register(DartTddStrategy())
        return registry
