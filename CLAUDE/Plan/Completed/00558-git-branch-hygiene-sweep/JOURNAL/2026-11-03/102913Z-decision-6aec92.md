## 10:29 · decision · —

Phase 1 design recorded in DESIGN.md (Tasks 1.1 and 1.2).

- Config: one top-level `branches:` block (default, remote, integration_lines, exempt, protected_names, wip, duplicates, dormancy, stop_guard, cleanup_after_merge, sweep), following the `reference_repos:` precedent of one block feeding hooks and CLI. `git_sync.default_branch` becomes the `auto` resolver behind a new `resolve_default_branch`; the `delete-branch`/`worktree-reap` defaults resolve through it; `branch_count_advisor`'s two options are renamed in the config-changes manifest with a one-release fallback read. Rejected: per-handler options, extending `worktree:`, `daemon:` keys, auto-detect only.
- Inventory: four to six git processes per pass whatever the branch count (`for-each-ref` with `%(ahead-behind:)` and park trailers, `worktree list`, `for-each-ref --merged` per target); per-branch `git cherry`/shortstat bounded by a (tip, target) cache and a wall-clock budget. Delete proofs reuse branch_safety's classify_branch/delete_branches, widened to integration-line targets.
- WIP cap: one `for-each-ref`, distinct tips of non-default, non-integration, non-exempt branches, local and remote; merged-but-undeleted and parked count. Routes: Bash switch -c/checkout -b/branch/worktree add (including the bare DWIM form), Agent isolation worktree, WorktreeCreate (backstop, non-zero exit). Unparseable commands are allowed.
- Dormancy: 14-day noisy = every SessionStart, every creation decision, main Stop context at most hourly; 30-day block denies creation routes only.
- Parked marker: empty commit with a `Parked-Reason:` trailer via `branch-park` (commit-tree + update-ref + fast-forward push). Rejected: tracked file, git note, plan file, local config.
- Creator record: `branch.<name>.hooksDaemon*` git config (removed/renamed by git with the branch, shared across worktrees). Rejected: untracked state file, reflog, name encoding, judging all branches.
- Stop guard: dirty blocks; unpushed blocks on the main thread and is advisory for sub-agents by default (this repository's sub-agents commit but do not push); merged-not-deleted blocks. Yields to usage pause and release gates, waives all but dirty on the context-budget handoff path, gives way after 3 blocks.
- Cleanup: local proof + worktree remove + branch -d in the hook; the remote delete is advised, proven later by R-GIT-PUSH-DELETE-REMOTE, which gains integration lines and one batched ls-remote (#153).
- Order: new Task 2.0 (config) first; Phase 3 builds 3.4, 3.1, 3.2, 3.3.
- Open for the owner (Q5): Worktree.md's "at most 3" versus the cap of 10; sub-agent unpushed advisory.
