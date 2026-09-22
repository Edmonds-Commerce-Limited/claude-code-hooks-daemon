"""SubagentStop handlers for claude-code-hooks-daemon.

Empty from Plan 00237 until Plan 00307 Task 3.1 dropped in
``SubagentReportSizeBlockerHandler`` — its predecessors
(``subagent_completion_logger``, ``remind_prompt_library``) were removed for
appending to a log nothing read and unconditionally advising a command/doc
that does not exist in this repository. Plan 00416 Task 1.1 adds
``CronSubagentStopEnforcerHandler``, the SubagentStop twin of
``handlers.stop.cron_stop_enforcer`` -- a subagent-only session can reach
this event without the main-thread Stop event ever firing. Plan 00446 adds
``SubagentReportPathVerifierHandler``, the size blocker's sibling: that one
catches a report too big to survive the wire, this one catches a report the
agent said it wrote and did not.
"""

from .cron_subagent_stop_enforcer import CronSubagentStopEnforcerHandler
from .subagent_cache_aggregator import SubagentCacheAggregatorHandler
from .subagent_report_path_verifier import SubagentReportPathVerifierHandler
from .subagent_report_size_blocker import SubagentReportSizeBlockerHandler

__all__: list[str] = [
    "CronSubagentStopEnforcerHandler",
    "SubagentCacheAggregatorHandler",
    "SubagentReportPathVerifierHandler",
    "SubagentReportSizeBlockerHandler",
]
