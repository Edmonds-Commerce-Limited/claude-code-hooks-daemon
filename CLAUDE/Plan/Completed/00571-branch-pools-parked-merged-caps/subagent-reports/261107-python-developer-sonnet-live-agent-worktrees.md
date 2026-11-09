# Report: branch-sweep --clean must leave live agents' worktrees alone

Defect: `branch-sweep --clean [--remote]` offered to remove a freshly spawned
isolation worktree (branch at main's tip, clean tree) and delete its branch.

## Fix

- New `core/agent_ownership.py`: `running_holds(untracked)` (reuses
  `work_queue.read_queue`/`active_records`, the records Task 2.5's stop guard
  treats as handed over), `ownership_refusal(...)` with three signals: a running
  work-queue record naming the branch or worktree, a worktree directly under
  `.claude/worktrees/`, a git `locked` marker.
- `branch_cleanup.clean_sweep` skips an owned branch and worktree with
  `Skipped <name>: ...`, and excludes it from the `--remote` candidates
  (`_proven_remote(spared=...)`). New `untracked` keyword (default: the daemon's
  untracked dir) so tests can point at a queue.
- Same-class paths checked:
  - `worktree-reap --reap/--reap-branches` (`cmd_worktree_reap`): now keeps
    work-queue-running and locked worktrees (KEEP) and does not prune a
    queue-running orphan branch. The harness-directory signal is deliberately NOT
    applied there, because reaping those worktrees is its job (it has age and
    live-process checks).
  - `delete-branch`: already refuses a branch checked out in any linked worktree
    (REFUSAL_WORKTREE), no change.
  - `cleanup_after_merge` (post-merge handler): only advises for worktree-held
    branches, no change. `delete_if_merged` runs after the worktree is gone.
- Not done: `branch_stop_gate._running_queue_branches` still has its own copy of
  the queue read (could delegate to `running_holds(...).branches`).

## Tests (written first, failed first)

`tests/unit/core/test_agent_ownership.py`,
`tests/unit/core/test_branch_cleanup_agent_owned.py` (real repos, incl. remote
sparing), `tests/unit/daemon/test_cli_worktree_reap_running_agent.py`. One
existing test (`test_a_locked_worktree_refusal_is_reported_verbatim`) pinned the
old behaviour (git's refusal text) and now expects the earlier "locked by git" skip.

## Docs

`docs/guides/CONFIGURATION.md` (branches section) and release-note callout
`005-branch-recovery-bundles-and-remote-clean.md`.

## QA

`llm_qa.py changed --allow-unmapped`: QA: 42/42 PASSED (run with the worktree's own
venv built by `bin/hooks-daemon repair`).
