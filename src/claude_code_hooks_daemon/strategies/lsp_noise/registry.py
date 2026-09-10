"""LSP-noise Strategy Registry - the full set of per-language strategies."""

from __future__ import annotations

from claude_code_hooks_daemon.strategies.lsp_noise.protocol import LspNoiseStrategy


class LspNoiseStrategyRegistry:
    """Registry of every language's LSP-noise strategy.

    Supports registering strategies, listing all registered strategies, and
    creating a default registry with every built-in language strategy.
    """

    def __init__(self) -> None:
        self._strategies: list[LspNoiseStrategy] = []

    def register(self, strategy: LspNoiseStrategy) -> None:
        """Register a strategy."""
        self._strategies.append(strategy)

    @property
    def strategies(self) -> list[LspNoiseStrategy]:
        """Every registered strategy, in registration order."""
        return list(self._strategies)

    @property
    def language_names(self) -> list[str]:
        """Names of all registered languages, in registration order."""
        return [strategy.language_name for strategy in self._strategies]

    @classmethod
    def create_default(cls) -> LspNoiseStrategyRegistry:
        """Create a registry with ALL built-in language strategies."""
        # Lazy imports to avoid circular dependencies.
        from claude_code_hooks_daemon.strategies.lsp_noise.go_strategy import GoLspNoiseStrategy
        from claude_code_hooks_daemon.strategies.lsp_noise.php_strategy import (
            PhpLspNoiseStrategy,
        )
        from claude_code_hooks_daemon.strategies.lsp_noise.python_strategy import (
            PythonLspNoiseStrategy,
        )
        from claude_code_hooks_daemon.strategies.lsp_noise.rust_strategy import (
            RustLspNoiseStrategy,
        )
        from claude_code_hooks_daemon.strategies.lsp_noise.typescript_strategy import (
            TypeScriptLspNoiseStrategy,
        )

        registry = cls()
        registry.register(PythonLspNoiseStrategy())
        registry.register(TypeScriptLspNoiseStrategy())
        registry.register(GoLspNoiseStrategy())
        registry.register(RustLspNoiseStrategy())
        registry.register(PhpLspNoiseStrategy())
        return registry
