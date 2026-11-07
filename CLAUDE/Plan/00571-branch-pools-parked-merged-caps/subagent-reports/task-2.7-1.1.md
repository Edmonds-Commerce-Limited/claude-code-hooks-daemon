# Plan 00571 Tasks 2.7 and 1.1: sub-agent report

## Task 2.7: remote-proof helpers reconciled

(a) `branch-sweep --clean --remote` never listed the remote twice in one run: the
clean path builds its inventory without `remote_refs`, and its only `ls-remote` is
inside the shared proof. But that proof (`core/remote_branch_proof.py`
`live_remote_tips`) had its own `ls-remote` call and parser beside Plan 00570's
`utils/remote_refs.py`. Fixed:

- `utils/remote_refs.list_remote_refs` takes keyword `patterns` and `timeout`
  (defaults unchanged: whole listing, `Timeout.GIT_LS_REMOTE`).
- `live_remote_tips` lists through it, bounded to `refs/heads/<name>` patterns, on
  `Timeout.GIT_CONTEXT` (the hook guard runs the same proof). Chunking and
  fail-closed behaviour are unchanged.
- The module docstring of `remote_refs` now names this hook-path caller.

(b) `core/branch_stop_gate._running_queue_branches(repo, untracked)` delegates to
`agent_ownership.running_holds(untracked, repo)`. The stop gate no longer reads the
queue itself. It also honours worktree holds: a branch checked out in a worktree that
a `running` record names, in any path spelling, is handed over. Before this change only the
record's branch field counted.

Tests (written first, RED confirmed):

- `tests/unit/utils/test_remote_refs.py`: patterns and timeout reach `ls-remote`.
- `tests/unit/core/test_remote_branch_proof.py`: the proof uses
  `list_remote_refs` with the judged pattern and hook timeout, and a failed listing
  proves nothing.
- `tests/unit/core/test_branch_stop_gate.py`: a relative, trailing-slash worktree
  hold hands its branch over, and the gate calls `running_holds(untracked, repo)`.
- `test_destructive_git_remote_delete_{batched,lines}.py`: their fake git now also
  patches `remote_refs.run_git` (the git seam moved; assertions are unchanged).

## Task 1.1: DESIGN.md

The design was already drafted. This pass added evidence and the open item:

- Real counts from `branch-sweep --all`: open work 8 of 10, 4 of them `dependabot/*`
  remote-only branches; 1 parked (2 days); 2 merged (live agent worktrees). With the five
  58-day merged branches from #165, the defaults work as follows.
- Defaults derive from owner values only. Caps default to `wip.cap`
  (`models.py:2268`). Max ages default to the dormancy preset's `block_days`
  (`models.py:2254-2257`, 30 or 7). An unkept merged branch has no allowance.
- Keep-reason store: a git note under `refs/notes/hooks-daemon/keep`, read
  offline, and fetched before `--clean --remote` judges.
- Re-park and re-keep need a new reason, and the count is visible from history.
- New §7: `branches.bot_owned: ["dependabot/*"]` puts a matching branch in no pool,
  and `--clean` never deletes it. It is a separate key from `exempt`, so a
  project's own `exempt` list cannot drop it.
- Migration: seven additive keys go in a config-changes entry. Three truth changes
  go in a truth-changes entry, with citations to `00558 DESIGN.md:137` and
  `CONFIGURATION.md:346`.
