# Report: issue #161 nested worktree root (Plan 00566)

## Finding: the brief's premise is false on current main; I did NOT change the handler

`WorktreeCreateHandler._repo_root` already anchors on the MAIN checkout:
`GitRepo.resolve_for(cwd).main_worktree_root()` (first record of `git worktree list --porcelain`). It was added by
Plan 00474 / N563 (commit dc45486fa, 2026-10-31) and is in tags v3.72.0 and v3.72.1. The worktree path, branch cap,
seed validation, creator record and seeding all use that one `root`, so there is nothing left to anchor. The issue
reporter ran 3.71.0 (the report calls it the newest release, which is stale); its line numbers (handler:113) do not
match main.

## Evidence

I wrote the end-to-end nested reproduction with real git (symlink-mode seeds, one file and one directory; outer
worktree created through the handler, then the handler invoked with cwd inside it) plus a test that a seed escaping
the repository is still rejected. Run against UNMODIFIED main code they PASS, so there is no red phase to quote:

```
pytest ... -k Nested  ->  2 passed, 45 deselected
whole file            ->  47 passed
```

Tests added (class `TestNestedWorktreeCreation` in
tests/unit/handlers/worktree_create/test_worktree_create_handler.py):

- inner worktree lands under `<main>/.claude/worktrees`, nothing is created under the outer worktree, and the inner
  seeds resolve to the main checkout.
- a seed that is a symlink to outside the repo is still rejected ("outside the repository root") from a nested cwd,
  and no inner worktree is left behind.

They are a regression guard for already-fixed behaviour (the existing N563 tests only used copy mode).

## Not done, deliberately

- No release-note callout (it would have been 002): no behaviour changes on this branch, and a callout claiming one
  would be false. Issue #161 should be answered with "fixed in v3.72.0 (N563); upgrade from 3.71.0".
- PLAN.md untouched. Its goals describe a fix that is not needed; the coordinator should close the plan as
  already-delivered and adjust its Success Criteria (the holding-area criterion in particular).

## Caveat

I did not reproduce the reporter's exact layout (main repo nested inside another repo under untracked/scratch).
My layout is a standard main plus linked worktree. The code path (first `worktree list` record) does not depend
on it.

## QA

`llm_qa.py changed --range main..HEAD` did NOT run: the host-wide QA lock was held for two full 600s waits by pid
3929899 (worktree-issue-162-lsp-extless), exit 4. Done instead: run_autofix.sh (clean) and pytest of the whole
handler test file (47 passed). The coordinator should run targeted QA for this test-only change.
