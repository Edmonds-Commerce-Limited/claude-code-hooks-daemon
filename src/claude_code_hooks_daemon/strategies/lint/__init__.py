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

from typing import TYPE_CHECKING

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy

if TYPE_CHECKING:
    # Type-checker-only binding: satisfies pyright's __all__ re-export check
    # (reportUnsupportedDunderAll) without executing at import time, so the
    # runtime lazy-import via __getattr__ below -- which exists to avoid a
    # circular import -- is unaffected. See test_init_lazy_import.py, which
    # pins the runtime __getattr__ behaviour this must not change.
    from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

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
