"""Comment syntax strategies for multi-language support.

Strategy Pattern implementation: each language supplies comment SYNTAX data
(line prefixes, block/doc delimiters) via a CommentStrategy. Extraction and
matching logic live once, shared, in ``extractor.py`` and the
``comment_size``/``comment_changelog`` handlers.

Usage:
    from claude_code_hooks_daemon.strategies.comments import (
        CommentStrategy,
        CommentStrategyRegistry,
    )

    registry = CommentStrategyRegistry.create_default()
    strategy = registry.get_strategy("/path/to/file.py")
    if strategy is not None:
        spans = extract_comment_spans(content, strategy.syntax)
"""

from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.registry import (
    CommentStrategyRegistry,
)

__all__ = [
    "CommentStrategy",
    "CommentStrategyRegistry",
]
