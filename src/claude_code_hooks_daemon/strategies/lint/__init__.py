"""Lint enforcement strategies for multi-language support.

Strategy Pattern implementation: each language has its own LintStrategy
that encapsulates all language-specific lint enforcement logic.

Usage:
    from claude_code_hooks_daemon.strategies.lint import LintStrategy, LintStrategyRegistry

    registry = LintStrategyRegistry.create_default()
    strategy = registry.get_strategy("/path/to/file.py")
    if strategy is not None:
        command = strategy.default_lint_command
"""

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy

__all__ = [
    "LintStrategy",
    "LintStrategyRegistry",
]


def __getattr__(name: str) -> type:
    """Lazy import for LintStrategyRegistry to avoid circular imports."""
    if name == "LintStrategyRegistry":
        from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

        return LintStrategyRegistry
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
