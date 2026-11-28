# Callout: a branch a live sub-agent is working on is "in flight" at stop, not abandoned

**Plan**: 00474
**Audience**: everyone

The branch stop guards (R-BRANCH-STOP-GUARD and R-BRANCH-SUBAGENT-STOP-GUARD) no longer hold a stop, or record a branch as abandoned or left unpushed after three blocks, when a live background sub-agent of the same session is working on that branch. This covers the lead stopping to wait for a developer agent that is still editing the shared worktree. Such a branch is reported as `Branch in flight (not abandoned): <branch>: a live agent of this session is working on it: <name> (<agent id>)`, recorded under `in_flight` in the guard's session state, and draws no block. While any other sub-agent of the session is live, a dirty finding's remedies never suggest `git add -A`: they say to stage only your own paths by name, or to wait for that agent, stop it, or have it commit its own work.

A sub-agent counts as live only on state the daemon can verify. It must be on the branch's touch record for this session, and its transcript must have moved within `Timeout.STOP_GUARD_AGENT_SILENCE` (the longest foreground Bash call plus a minute, 11 minutes). Its turn must not have ended, its transcript must be readable, and neither a recorded nor the current `background_tasks` list may report it as no longer running. Any other case is judged exactly as before. That includes a stop payload with no transcript path, an agent that finished, failed or went silent, and an agent of another session. A stopping sub-agent's own transcript never keeps its own branch in flight.

**Limit:** the touch record says an agent touched the branch in this session, not which of the dirty files are its own. A live agent that touched the branch earlier in the session keeps it in flight while it works elsewhere, until it finishes or goes silent past the bound.
