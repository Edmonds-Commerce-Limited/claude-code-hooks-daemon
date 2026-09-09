# Callout: the supervisor release-review ledger is worked to zero

**Plan**: 00319
**Audience**: operators

All ten supervisor findings from the v3.60.0 review and the six observations
from its acceptance run are fixed. What an operator notices: the budget
exhaustion detector no longer fires on a QUOTED budget message (a sub-agent
report, a Bash command that only passes content through, a ledger record
being written), only on one actually delivered to the session; the audit
banner no longer clobbers a live Ctrl+C hint; the worker error log is capped
like `decision.log`; a worker swap that drops a half-typed slash command
leaves a trace instead of vanishing it; and `pipe_blocker` names the real
producer of a piped `python -m pytest`. Every BLOCKING acceptance test now
carries a structured payload that the integration suite drives through the
real handler, so a handler's declared deny patterns cannot drift from what
it prints.
