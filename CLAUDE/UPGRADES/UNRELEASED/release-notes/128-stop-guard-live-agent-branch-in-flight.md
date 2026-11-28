# Callout: a dirty worktree a live sub-agent is working in is "in flight" at stop, not abandoned

**Plan**: 00474
**Audience**: everyone

The branch stop guards (R-BRANCH-STOP-GUARD and R-BRANCH-SUBAGENT-STOP-GUARD) no longer hold a stop on a branch's dirty worktree, or record that branch as abandoned after three blocks, when a live background sub-agent of the same session is working on the branch. This covers the lead stopping to wait for a developer agent that is still editing the shared worktree. The dirty-worktree finding is reported as `Branch in flight (not abandoned): <branch>: its dirty worktree belongs to a live agent of this session: <name> (<agent id>)` and recorded under `in_flight` in the guard's session state. The record is cleared by the next stop that finds nothing in flight. **Only the dirty-worktree finding goes in flight.** Every other finding on that branch is held and reported exactly as before, because none of them touches the agent's files: the lead's unpushed commits (`git push`), a merged branch not deleted, dormancy and the open-pool cap.

While any other sub-agent of the session is live, a held dirty finding's remedies never suggest `git add -A`. They say to stage only your own paths by name, or to wait for that agent, stop it, or have it commit its own work.

A sub-agent counts as live only on state the daemon can verify:

- It must be on the branch's touch record for this session.
- Its transcript must have moved within `Timeout.STOP_GUARD_AGENT_SILENCE`: the longest foreground Bash call plus a minute, 11 minutes.
- The transcript must not be dated more than `Timeout.TRANSCRIPT_CLOCK_SKEW` (5 seconds) in the future, and must not be a symlink.
- Its turn must not have ended.
- The transcript must be readable and must hold a real record. A fresh agent counts once its prompt is on disk; an empty, binary or unparseable file does not count.
- Neither a recorded nor the current `background_tasks` list may report it as no longer running.

Any other case is judged exactly as before. That includes a stop payload with no transcript path, an agent that finished, failed or went silent, and an agent of another session. A stopping sub-agent's own transcript never keeps its own branch in flight.

The reads are bounded. Nothing is read unless a dirty finding would hold the stop. Only the dirty branches' authors are read first, and at most one more agent is looked for when a dirty finding is still held. All of it shares `Timeout.STOP_GUARD_LIVE_AGENT_READ_BUDGET` (2 seconds). An agent left unread when the budget runs out is not live, so the stop is judged as before.

**Limit:** the touch record says an agent touched the branch in this session, not which of the dirty files are its own. A live agent that touched the branch earlier in the session keeps its dirty worktree in flight while it works elsewhere, until it finishes or goes silent past the bound.
