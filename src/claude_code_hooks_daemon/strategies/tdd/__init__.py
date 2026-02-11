"""TDD enforcement strategies for multi-language support.

Strategy Pattern implementation: each language has its own TddStrategy
that encapsulates all language-specific TDD enforcement logic.

Usage:
    from claude_code_hooks_daemon.strategies.tdd import TddStrategy, TddStrategyRegistry

    registry = TddStrategyRegistry.create_default()
    strategy = registry.get_strategy("/path/to/file.py")
    if strategy is not None:
        is_test = strategy.is_test_file(file_path)
"""

from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy
from claude_code_hooks_daemon.strategies.tdd.registry import TddStrategyRegistry

__all__ = [
    "TddStrategy",
    "TddStrategyRegistry",
]
