"""SubagentStop handlers for claude-code-hooks-daemon.

Empty from Plan 00237 until Plan 00307 Task 3.1 dropped in
``SubagentReportSizeBlockerHandler`` — its predecessors
(``subagent_completion_logger``, ``remind_prompt_library``) were removed for
appending to a log nothing read and unconditionally advising a command/doc
that does not exist in this repository.
"""

from .subagent_report_size_blocker import SubagentReportSizeBlockerHandler

__all__: list[str] = ["SubagentReportSizeBlockerHandler"]
