# Callout: stopping with branch work unfinished is now denied, three times at most

**Plan**: 00558
**Audience**: operators

Two new non-terminal handlers, `branch_stop_guard` (Stop, priority 9) and `branch_subagent_stop_guard` (SubagentStop, priority 12), judge the branches the stopping session or sub-agent touched, using the touch records.

- **Checks**: a dirty worktree, commits no remote holds, and a branch merged but not deleted. The deny names the branch, the failed check and the exact commands. The default branch and integration lines are skipped unless `branches.stop_guard.include_default` is set.
- **Scope**: a sub-agent answers for its own branches. The coordinator answers for its own and for its sub-agents' unpushed and merged-but-present branches, not their dirty worktrees. `branches.stop_guard.unpushed_subagent` (`block`, `advise`, `off`) sets how a sub-agent's unpushed commits are treated.
- **Gives way**: after three denied stops the guard allows the stop and records the branches as abandoned in the session's spend-ledger state. A live usage pause, a recorded release, or a git failure also allows the stop. An agent past its hard context budget skips the merged check and the deny lists each branch with its tip sha for the handoff.
- **Noisy line**: at a main-thread stop, at most once an hour per session, a non-blocking line lists branches at the noisy dormancy stage or later.
- `branches.stop_guard.mode` is `block` (default), `warn` or `off`.

Enable them with `handlers.stop.branch_stop_guard: {enabled: true, priority: 9}` and `handlers.subagent_stop.branch_subagent_stop_guard: {enabled: true, priority: 12}`.
