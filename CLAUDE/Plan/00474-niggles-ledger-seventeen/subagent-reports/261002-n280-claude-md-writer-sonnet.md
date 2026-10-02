# N280 findings: who wrote an older CLAUDE.md guidance section into main

Verdict: lead 1 (a worktree resolves the project root through git's common dir)
is NOT supported by the code, and could not be reproduced. No source change was
made. What was ruled out, and what remains, is below.

## Writers of the generated section

There is exactly one writer of the `<hooksdaemon>` block: `ClaudeMdInjector`
(`src/claude_code_hooks_daemon/core/claude_md_injector.py`), constructed in one
place, `DaemonController.initialise()` (`daemon/controller.py`, around line 396).
`initialise()` is reached from two callers only:

- `_build_initialised_controller` in `daemon/cli.py`, used by `cmd_start` and
  `cmd_regenerate_docs`;
- `DaemonController.process_event`, which calls `initialise()` with no arguments
  and therefore raises (`workspace_root` is fail-fast required).

Nothing re-runs it on hot reload; the daemon injects at startup only.

## Root resolution

- `initialise()` takes `workspace_root` explicitly and never derives it.
- `cmd_regenerate_docs` resolves it with `get_project_path(args.project_root)`:
  an explicit root, else a walk up from `Path.cwd()` to the first `.claude/`.
- `bin/hooks-daemon` anchors `--project-root` from the wrapper's own location
  (`cd -P`), never from git. `init.sh` walks up from its own directory.
- `git rev-parse --git-common-dir` is used in `qa/full_qa_lock.py` (the host-wide
  lock), `scripts/setup_worktree.sh` (a nesting preflight), `llm_qa.py`,
  `run_tests.sh` and the `mkplan.bash` template. None of them writes CLAUDE.md or
  resolves a project root for a writer. `ProjectContext` uses `--show-toplevel`.
- The injector already refuses a linked worktree unless `regenerate-docs` asked
  for it, so even a worktree daemon would not write its own CLAUDE.md.

## Reproduction attempts (all negative)

Observed `/workspace/CLAUDE.md` mtime (1790926771) and `git diff --stat` before
and after each run, from the worktree at current main:

1. `tests/unit/daemon`, `test_claude_md_injector.py`, `test_pseudo_event.py`,
   `test_dependency_system.py`, `test_check_generated_doc_drift.py`: 2673 passed.
2. Thirteen integration and script test files that initialise a controller or call
   the injector: 781 passed.
3. The same writer-adjacent files run with the working directory outside the
   checkout (`/workspace/untracked/worktrees`, where a cwd walk-up reaches
   `/workspace/.claude`) and the worktree's code on `pythonpath`: passed.

mtime and content of the main CLAUDE.md never changed. So no test in the checked
set writes the main checkout from a worktree, by either root resolution or a
cwd walk-up.

## Timeline from main's history

- 21:54:03 Merge of N271 (`85bea8da6`).
- 21:55:54 `f387c9f7d` "Auto: hooks daemon regenerated CLAUDE.md": the injector
  committed the N271 row, so main's daemon (or a restart) wrote the NEW text.
- About 22:02:09 the guard preserved a copy carrying the pre-N271 row
  (`untracked/rejected-writes/CLAUDE.md.rejected`, mtime 22:02:09).

So the older text appeared in the file AFTER main had already regenerated it.

## What remains, unproven

The conftest guard (`no_test_writes_tracked_generated_docs`) restores each
protected file to its per-test START baseline. If a legitimate external change
lands inside a test's window (here, a merge or regeneration carrying the N271
text), the guard sees a changed fingerprint, preserves the new bytes, and writes
back the older baseline. That makes the guard itself a source of OLDER content in
the main checkout, run by whichever checkout's pytest is active, with no
`ClaudeMdInjector` involved. It fits "older than main, repeated, in unrelated
tests, daemon pid unchanged". It does not fit the preserved copy being the old
text unless the first restore had already put old text back and a second external
write followed; I could not confirm that sequence.

The earlier daemon-pid evidence cannot rule out lead 2 either: a second daemon
whose root resolves to the enclosing repository would not touch main's pid file.
The code gives no route for that (see Root resolution), so it is unconfirmed, not
excluded.

## Suggested next step

Record the restore-to-baseline behaviour as a candidate cause in the ledger, and
decide whether the guard should stop restoring when `git show HEAD:<file>` equals
the post-test bytes (a regeneration that agrees with HEAD is not a test write).
That is a behaviour change to the guard the owner should approve; it was not made
here.

## Side note

One of my commands wrote its capture to `/workspace/untracked/scratch/n280-run4.txt`
(the main checkout's gitignored scratch dir) instead of the worktree's. It is a
test log only and can be deleted.
