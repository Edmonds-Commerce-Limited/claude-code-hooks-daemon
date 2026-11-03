# Callout: branches record who created and who touched them, and WorktreeRemove trusts the record

**Plan**: 00558
**Audience**: operators

The new `branch_touch_recorder` PostToolUse handler writes two records into the repository's git config.

- **Creator**: after a git command creates a branch (`switch -c`, `checkout -b`, `branch <name>`, `worktree add`), once the ref exists and only when no creator is recorded yet, it writes `branch.<name>.hooksDaemonCreator` (`<session>:<agent>`, the agent empty on the main thread), `hooksDaemonCreated` (unix time) and `hooksDaemonRoute`. The WorktreeCreate event writes the same record itself with route `worktree_create`. An agent's first touch of a branch its own session's main thread made through WorktreeCreate binds the creator to that agent.
- **Touches**: a `commit`, `merge`, `rebase`, `cherry-pick`, `am`, `revert`, `reset`, `switch`, `checkout` or `pull`, and any Write/Edit/NotebookEdit, adds the session and agent to the checked-out branch's `hooksDaemonTouchedBy`, once per branch per session. A failed write is logged and never blocks.
- **WorktreeRemove** now deletes a merged branch when its creator route is `worktree_create`. Only a branch with no record at all is still judged by its `<slug>-<8 hex>` name, and a branch recorded with any other route is kept.
- The WorktreeCreate budget grows by three short git calls, so the `.claude/init.sh` client wait for WorktreeCreate is now 85 seconds.

Enable it with `handlers.post_tool_use.branch_touch_recorder: {enabled: true, priority: 40}`.
