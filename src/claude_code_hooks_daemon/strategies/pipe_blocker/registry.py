"""PipeBlockerStrategyRegistry - maps language names to strategy implementations."""

from claude_code_hooks_daemon.strategies.pipe_blocker.protocol import PipeBlockerStrategy

# Universal strategy is always active — never filtered by language setting
_UNIVERSAL_LANGUAGE_NAME = "Universal"


class PipeBlockerStrategyRegistry:
    """Registry mapping language names to pipe-blocker strategy implementations.

    Unlike the TDD/Lint registries (which map file extensions → strategies),
    this registry maps language_name → strategy and merges blacklist patterns
    from all active strategies into a flat list for O(n) matching.

    The Universal strategy is ALWAYS active and cannot be filtered out.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, PipeBlockerStrategy] = {}

    def register(self, strategy: PipeBlockerStrategy) -> None:
        """Register a strategy by its language_name."""
        self._strategies[strategy.language_name] = strategy

    def get_blacklist_patterns(self) -> tuple[str, ...]:
        """Merge blacklist patterns from ALL active strategies into flat tuple."""
        patterns: list[str] = []
        for strategy in self._strategies.values():
            patterns.extend(strategy.blacklist_patterns)
        return tuple(patterns)

    def filter_by_languages(self, language_names: list[str]) -> None:
        """Remove strategies not in the given list.

        Universal strategy is ALWAYS kept regardless of the filter.
        Matching is case-insensitive. Empty list = no filtering applied.
        """
        if not language_names:
            return
        allowed = {name.lower() for name in language_names}
        allowed.add(_UNIVERSAL_LANGUAGE_NAME.lower())  # Universal is always kept
        to_remove = [lang for lang in self._strategies if lang.lower() not in allowed]
        for lang in to_remove:
            del self._strategies[lang]

    @property
    def registered_languages(self) -> list[str]:
        """Get names of all registered languages."""
        return list(self._strategies.keys())

    @classmethod
    def create_default(cls) -> "PipeBlockerStrategyRegistry":
        """Create registry with ALL built-in language strategies."""
        # Lazy imports to avoid circular dependencies
        from claude_code_hooks_daemon.strategies.pipe_blocker.go_strategy import (
            GoPipeBlockerStrategy,
        )
        from claude_code_hooks_daemon.strategies.pipe_blocker.java_strategy import (
            JavaPipeBlockerStrategy,
        )
        from claude_code_hooks_daemon.strategies.pipe_blocker.javascript_strategy import (
            JavaScriptPipeBlockerStrategy,
        )
        from claude_code_hooks_daemon.strategies.pipe_blocker.python_strategy import (
            PythonPipeBlockerStrategy,
        )
        from claude_code_hooks_daemon.strategies.pipe_blocker.ruby_strategy import (
            RubyPipeBlockerStrategy,
        )
        from claude_code_hooks_daemon.strategies.pipe_blocker.rust_strategy import (
            RustPipeBlockerStrategy,
        )
        from claude_code_hooks_daemon.strategies.pipe_blocker.shell_strategy import (
            ShellPipeBlockerStrategy,
        )
        from claude_code_hooks_daemon.strategies.pipe_blocker.universal_strategy import (
            UniversalPipeBlockerStrategy,
        )

        registry = cls()
        registry.register(UniversalPipeBlockerStrategy())
        registry.register(PythonPipeBlockerStrategy())
        registry.register(JavaScriptPipeBlockerStrategy())
        registry.register(ShellPipeBlockerStrategy())
        registry.register(GoPipeBlockerStrategy())
        registry.register(RustPipeBlockerStrategy())
        registry.register(JavaPipeBlockerStrategy())
        registry.register(RubyPipeBlockerStrategy())
        return registry
