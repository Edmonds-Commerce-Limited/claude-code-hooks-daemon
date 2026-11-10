# Issue 173 implementer report (Plan 00592, Task 1.1)

## RED

Five new tests in `TestUndoOfALockedPartialAdd` (tests/unit/handlers/worktree_create/test_worktree_create_handler.py), real tmp git repo, lock simulated with `git worktree lock --reason`. Before the change the initializing case logged `fatal: cannot remove a locked working tree, lock reason: initializing` and `error: cannot delete branch 'wb' used by worktree`; the error-text test failed with `assert '<path>' in "Command '['git']' returned non-zero exit status 128.: fatal: add failed"`.

## GREEN

`worktree_create_handler.py`:

- `_lock_reason(cwd, path)` parses `worktree list --porcelain` for the record whose `worktree` line equals the resolved path.
- `_undo_failed_add` runs `worktree unlock` first only when the reason is exactly `initializing`. Any other lock: nothing is touched and a warning is logged. No `remove -f -f`.
- `_undo_failed_add` now returns a description of what is still there (checked by path/registry and `rev-parse` on the branch), `""` when clean.
- `_WorktreeAddError.left_behind` carries it and `__str__` appends `[worktree left behind at P; branch left behind: B]`.

Why this way: the raised error is the only thing the caller sees (the hook's stderr), so putting the leftovers in its text is the least invasive route; the signature change of a private static method is the only API change. A cleanup failure still never masks the add error.

## Verification

52 tests in tests/unit/handlers/worktree_create pass. Release note: 026-worktree-create-undo-releases-initializing-lock.md.

## Disagreements

None with the brief.
