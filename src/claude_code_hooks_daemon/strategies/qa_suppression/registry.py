"""QA Suppression Strategy Registry - maps file extensions to strategy implementations."""

from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)


class QaSuppressionStrategyRegistry:
    """Registry mapping file extensions to QA suppression strategy implementations.

    Supports:
    - Registering strategies by their declared extensions
    - Looking up strategy for a file path
    - Listing all registered strategies
    - Creating a default registry with all built-in strategies
    """

    def __init__(self) -> None:
        self._strategies: dict[str, QaSuppressionStrategy] = {}

    def register(self, strategy: QaSuppressionStrategy) -> None:
        """Register a strategy for all its declared extensions."""
        for ext in strategy.extensions:
            self._strategies[ext.lower()] = strategy

    def get_strategy(self, file_path: str) -> QaSuppressionStrategy | None:
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
    def create_default(cls) -> "QaSuppressionStrategyRegistry":
        """Create registry with ALL built-in language strategies."""
        # Lazy imports to avoid circular dependencies
        from claude_code_hooks_daemon.strategies.qa_suppression.csharp_strategy import (
            CSharpQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.dart_strategy import (
            DartQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.go_strategy import (
            GoQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.java_strategy import (
            JavaQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.javascript_strategy import (
            JavaScriptQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.kotlin_strategy import (
            KotlinQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.php_strategy import (
            PhpQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
            PythonQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.ruby_strategy import (
            RubyQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.rust_strategy import (
            RustQaSuppressionStrategy,
        )
        from claude_code_hooks_daemon.strategies.qa_suppression.swift_strategy import (
            SwiftQaSuppressionStrategy,
        )

        registry = cls()
        registry.register(PythonQaSuppressionStrategy())
        registry.register(GoQaSuppressionStrategy())
        registry.register(JavaScriptQaSuppressionStrategy())
        registry.register(PhpQaSuppressionStrategy())
        registry.register(RustQaSuppressionStrategy())
        registry.register(JavaQaSuppressionStrategy())
        registry.register(CSharpQaSuppressionStrategy())
        registry.register(KotlinQaSuppressionStrategy())
        registry.register(RubyQaSuppressionStrategy())
        registry.register(SwiftQaSuppressionStrategy())
        registry.register(DartQaSuppressionStrategy())
        return registry
