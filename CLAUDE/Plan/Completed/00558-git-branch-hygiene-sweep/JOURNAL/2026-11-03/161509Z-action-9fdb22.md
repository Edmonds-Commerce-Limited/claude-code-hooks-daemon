## 16:15 · action · —

Tasks 3.2 and 3.3 done on branch worktree-558-wtremove (not merged).

- WorktreeRemove maps the payload path through `git worktree list --porcelain`, removes only a linked worktree with no `worktree_blockers`, adds `--force` only when HEAD is held by another ref, then deletes a `<slug>-<8 hex>` branch through the new `branch_cleanup.delete_if_merged` (cheap `merge-base --is-ancestor` probe first, then `classify_branch` with `content_tier=False`, merged tiers only). No creator record exists yet (Task 4.2), so eligibility is the name shape; the log line says so. Every git call is capped by the event's handler budget; an exhausted budget skips and logs.
- `worktree-reap` orphan pruning widened from `agent-*` to `is_daemon_created_branch` (agent or WorktreeCreate name).
- Dogfood fixes: empty directories never block, a `store/` glob covers a symlink of that name, eight new regenerable defaults. On /workspace, read-only, the new defaults clear `.CLAUDE.md.pre-inject`, `untracked/.python-cmd-cache`, `untracked/context-sidecar/` and `untracked/logs/`. `branch-sweep --clean --dry-run` had no worktree candidate to show the change on ("Nothing to clean").
- SessionStart summary names work branches more than `branches.sweep.behind_threshold` behind the default (new sessions, inside the line cap); the legacy `behind_main_threshold` is the fallback.

Report: subagent-reports/261103-task32-33.md. Release note 027.
