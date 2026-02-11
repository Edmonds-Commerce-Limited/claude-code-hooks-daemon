"""QA suppression strategies for multi-language support.

Strategy Pattern implementation: each language has its own QaSuppressionStrategy
that encapsulates all language-specific QA suppression enforcement logic.

Usage:
    from claude_code_hooks_daemon.strategies.qa_suppression import (
        QaSuppressionStrategy,
        QaSuppressionStrategyRegistry,
    )

    registry = QaSuppressionStrategyRegistry.create_default()
    strategy = registry.get_strategy("/path/to/file.py")
    if strategy is not None:
        patterns = strategy.forbidden_patterns
"""

from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.registry import (
    QaSuppressionStrategyRegistry,
)

__all__ = [
    "QaSuppressionStrategy",
    "QaSuppressionStrategyRegistry",
]
