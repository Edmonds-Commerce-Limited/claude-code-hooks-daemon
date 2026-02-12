"""Lint Strategy Registry - maps file extensions to strategy implementations."""

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy


class LintStrategyRegistry:
    """Registry mapping file extensions to lint strategy implementations.

    Supports:
    - Registering strategies by their declared extensions
    - Looking up strategy for a file path
    - Listing all registered strategies
    - Creating a default registry with all built-in strategies
    """

    def __init__(self) -> None:
        self._strategies: dict[str, LintStrategy] = {}

    def register(self, strategy: LintStrategy) -> None:
        """Register a strategy for all its declared extensions."""
        for ext in strategy.extensions:
            self._strategies[ext.lower()] = strategy

    def get_strategy(self, file_path: str) -> LintStrategy | None:
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
    def create_default(cls) -> "LintStrategyRegistry":
        """Create registry with ALL built-in language strategies."""
        # Lazy imports to avoid circular dependencies
        from claude_code_hooks_daemon.strategies.lint.dart_strategy import DartLintStrategy
        from claude_code_hooks_daemon.strategies.lint.go_strategy import GoLintStrategy
        from claude_code_hooks_daemon.strategies.lint.kotlin_strategy import KotlinLintStrategy
        from claude_code_hooks_daemon.strategies.lint.php_strategy import PhpLintStrategy
        from claude_code_hooks_daemon.strategies.lint.python_strategy import PythonLintStrategy
        from claude_code_hooks_daemon.strategies.lint.ruby_strategy import RubyLintStrategy
        from claude_code_hooks_daemon.strategies.lint.rust_strategy import RustLintStrategy
        from claude_code_hooks_daemon.strategies.lint.shell_strategy import ShellLintStrategy
        from claude_code_hooks_daemon.strategies.lint.swift_strategy import SwiftLintStrategy

        registry = cls()
        registry.register(ShellLintStrategy())
        registry.register(PythonLintStrategy())
        registry.register(GoLintStrategy())
        registry.register(RustLintStrategy())
        registry.register(RubyLintStrategy())
        registry.register(PhpLintStrategy())
        registry.register(DartLintStrategy())
        registry.register(KotlinLintStrategy())
        registry.register(SwiftLintStrategy())
        return registry
