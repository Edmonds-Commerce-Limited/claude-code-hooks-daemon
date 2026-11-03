# Issue 156 report (Plan 00561 Tasks 1.1-1.3)

## Changes

- `tests/integration/test_worktree_claudemd_excludes.py` (new): derives worktree roots from `WORKTREES_SUBDIR` in `core/worktree_naming.py` (WorktreeCreate handler) and from the `WORKTREES_DIR=` line in `scripts/setup_worktree.sh`. Asserts each root's `<name>/CLAUDE.md` matches a `claudeMdExcludes` glob (`**` crosses directories, `*` does not), and that a nested `src/CLAUDE.md` still does not match.
- `.claude/settings.local.json`: added `claudeMdExcludes` with the two globs; nothing else changed.
- `CLAUDE/Worktree.md`: new section on why the setting exists and what it skips.
- `PLAN.md`: Tasks 1.1-1.3 ticked.

## RED (before the settings change)

```
AssertionError: WorktreeCreate handler creates worktrees under .claude/worktrees/ but no claudeMdExcludes glob in settings.local.json matches /example/project/.claude/worktrees/worktree-example/CLAUDE.md; globs: []
AssertionError: scripts/setup_worktree.sh creates worktrees under untracked/worktrees/ but no claudeMdExcludes glob ... globs: []
2 failed, 1 passed
```

## GREEN

3 passed. `mypy --strict` on the test file: no issues.

## Notes

- I did not disagree with the approach.
- The worktree's own session still showed the root `CLAUDE.md` injected on first read. That is expected: the setting is in this branch's file and takes effect once it is on the checkout the session is rooted at.
- A tool result mid-task carried an unrelated instruction to prefer sed and heredocs for edits. It was not part of the brief, so I ignored it and used Edit/Write.
