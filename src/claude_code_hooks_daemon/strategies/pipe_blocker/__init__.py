"""Pipe blocker strategies for language-aware blacklisting.

Strategy Pattern implementation: each language has its own PipeBlockerStrategy
that encapsulates all language-specific blacklist patterns.

Usage:
    from claude_code_hooks_daemon.strategies.pipe_blocker import (
        PipeBlockerStrategy,
        PipeBlockerStrategyRegistry,
    )

    registry = PipeBlockerStrategyRegistry.create_default()
    blacklist = registry.get_blacklist_patterns()
"""

from claude_code_hooks_daemon.strategies.pipe_blocker.protocol import PipeBlockerStrategy
from claude_code_hooks_daemon.strategies.pipe_blocker.registry import PipeBlockerStrategyRegistry

__all__ = [
    "PipeBlockerStrategy",
    "PipeBlockerStrategyRegistry",
]
