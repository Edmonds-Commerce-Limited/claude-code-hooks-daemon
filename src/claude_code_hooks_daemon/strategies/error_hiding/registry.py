"""ErrorHidingStrategyRegistry - maps file extensions to strategy implementations."""

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingStrategy


class ErrorHidingStrategyRegistry:
    """Registry mapping file extensions to error-hiding strategy implementations.

    Supports:
    - Registering strategies by their declared extensions
    - Looking up a strategy for a file path (by extension)
    - Filtering to a subset of languages
    - Creating a default registry with all built-in strategies
    """

    def __init__(self) -> None:
        # Maps normalised extension (lower-case) → strategy
        self._strategies: dict[str, ErrorHidingStrategy] = {}

    def register(self, strategy: ErrorHidingStrategy) -> None:
        """Register a strategy for all its declared extensions."""
        for ext in strategy.extensions:
            self._strategies[ext.lower()] = strategy

    def get_strategy(self, file_path: str) -> ErrorHidingStrategy | None:
        """Return the strategy for a file path based on its extension, or None."""
        file_path_lower = file_path.lower()
        for ext, strategy in self._strategies.items():
            if file_path_lower.endswith(ext):
                return strategy
        return None

    def filter_by_languages(self, language_names: list[str]) -> None:
        """Remove strategies whose language_name is not in the given list.

        Matching is case-insensitive.  If language_names is empty, no filtering
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
        """Return de-duplicated list of language names for all registered strategies."""
        seen: set[str] = set()
        result: list[str] = []
        for strategy in self._strategies.values():
            if strategy.language_name not in seen:
                seen.add(strategy.language_name)
                result.append(strategy.language_name)
        return result

    @classmethod
    def create_default(cls) -> "ErrorHidingStrategyRegistry":
        """Create a registry with ALL built-in language strategies."""
        # Lazy imports to avoid circular dependencies
        from claude_code_hooks_daemon.strategies.error_hiding.go_strategy import (
            GoErrorHidingStrategy,
        )
        from claude_code_hooks_daemon.strategies.error_hiding.java_strategy import (
            JavaErrorHidingStrategy,
        )
        from claude_code_hooks_daemon.strategies.error_hiding.javascript_strategy import (
            JavaScriptErrorHidingStrategy,
        )
        from claude_code_hooks_daemon.strategies.error_hiding.python_strategy import (
            PythonErrorHidingStrategy,
        )
        from claude_code_hooks_daemon.strategies.error_hiding.shell_strategy import (
            ShellErrorHidingStrategy,
        )

        registry = cls()
        registry.register(ShellErrorHidingStrategy())
        registry.register(PythonErrorHidingStrategy())
        registry.register(JavaScriptErrorHidingStrategy())
        registry.register(GoErrorHidingStrategy())
        registry.register(JavaErrorHidingStrategy())
        return registry
