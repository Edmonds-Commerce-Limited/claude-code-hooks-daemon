"""Comment Strategy Registry - maps file extensions to strategy implementations."""

from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy


class CommentStrategyRegistry:
    """Registry mapping file extensions to comment strategy implementations.

    Supports:
    - Registering strategies by their declared extensions
    - Looking up strategy for a file path
    - Listing all registered strategies
    - Creating a default registry with all built-in strategies
    """

    def __init__(self) -> None:
        self._strategies: dict[str, CommentStrategy] = {}

    def register(self, strategy: CommentStrategy) -> None:
        """Register a strategy for all its declared extensions."""
        for ext in strategy.extensions:
            self._strategies[ext.lower()] = strategy

    def get_strategy(self, file_path: str) -> CommentStrategy | None:
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

    @property
    def all_strategies(self) -> list[CommentStrategy]:
        """Get all DISTINCT registered strategy instances (deduplicated)."""
        seen: set[str] = set()
        result: list[CommentStrategy] = []
        for strategy in self._strategies.values():
            if strategy.language_name in seen:
                continue
            seen.add(strategy.language_name)
            result.append(strategy)
        return result

    @classmethod
    def create_default(cls) -> "CommentStrategyRegistry":
        """Create registry with ALL built-in language strategies."""
        # Lazy imports to avoid circular dependencies
        from claude_code_hooks_daemon.strategies.comments.csharp_strategy import (
            CSharpCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.dart_strategy import (
            DartCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.go_strategy import (
            GoCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.java_strategy import (
            JavaCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.javascript_strategy import (
            JavaScriptCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.kotlin_strategy import (
            KotlinCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.php_strategy import (
            PhpCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.python_strategy import (
            PythonCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.ruby_strategy import (
            RubyCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.rust_strategy import (
            RustCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.shell_strategy import (
            ShellCommentStrategy,
        )
        from claude_code_hooks_daemon.strategies.comments.swift_strategy import (
            SwiftCommentStrategy,
        )

        registry = cls()
        registry.register(PythonCommentStrategy())
        registry.register(ShellCommentStrategy())
        registry.register(RubyCommentStrategy())
        registry.register(JavaScriptCommentStrategy())
        registry.register(GoCommentStrategy())
        registry.register(PhpCommentStrategy())
        registry.register(JavaCommentStrategy())
        registry.register(CSharpCommentStrategy())
        registry.register(KotlinCommentStrategy())
        registry.register(RustCommentStrategy())
        registry.register(SwiftCommentStrategy())
        registry.register(DartCommentStrategy())
        return registry
