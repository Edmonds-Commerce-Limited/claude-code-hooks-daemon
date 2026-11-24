"""Lane-command strategies: each language's common test, build, lint and QA commands.

Strategy Pattern implementation feeding host_seat_lane_guard. Each language
keeps a SHORT list; the long tail of wrapper spellings is deliberately not
chased (Plan 00635 owner ruling).

Usage:
    from claude_code_hooks_daemon.strategies.lane_commands import (
        LaneCommandStrategyRegistry,
    )

    patterns = LaneCommandStrategyRegistry.create_default().get_lane_patterns()
"""

from claude_code_hooks_daemon.strategies.lane_commands.protocol import LaneCommandStrategy
from claude_code_hooks_daemon.strategies.lane_commands.registry import (
    LaneCommandStrategyRegistry,
)

__all__ = [
    "LaneCommandStrategy",
    "LaneCommandStrategyRegistry",
]
