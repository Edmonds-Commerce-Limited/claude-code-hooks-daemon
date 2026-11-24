# Callout: a coordinator's unexplained stop around running background agents now says how to wind down

**Plan**: 00636
**Audience**: operators

On a team coordinator seat, a stop with no `STOPPING BECAUSE:` line is still refused (`R-STOP-NO-REASON`), but when the Stop payload reports background tasks with status `running`, the refusal now ends with a wind-down note. It names the running tasks (up to five ids, and how many more) and gives one stop line that passes: `STOPPING BECAUSE: N background tasks are still running; their completion notices resume this session.` It also says a finished teammate is still listed as running, so `ListAgents` first and `TaskStop` the harvested ones. The suggested line carries no waiting-on-a-human wording, so it does not arm the awaiting-human marker or `owner_wait_stop_guard`.

Nothing is allowed that was refused before, and no new refusal is added. The note never appears on its own, because a Stop allow that carries text makes Claude Code continue the turn. A declared worker, a session with no team, a sub-agent, and a payload with no running task (field absent, empty or malformed) get the refusal unchanged. No config change.
