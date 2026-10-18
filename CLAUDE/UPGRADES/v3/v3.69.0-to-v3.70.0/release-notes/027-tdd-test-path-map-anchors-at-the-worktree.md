# Callout: `tdd_enforcement` checks a worktree's own test against a declared `test_path_map`

**Plan**: 00505
**Audience**: operators

A source file written inside a git worktree nested in the project (`untracked/worktrees/<name>/`) was checked against the main checkout's `test_path_map` directory, so the test written in the worktree was never searched and the write was denied with R-TDD-TEST-FIRST. A declared `test_dir`, flat or `mirror: true`, and the `source_glob` that selects it are now anchored at the checkout that holds the source file, so the worktree's own test satisfies the gate and the deny names the worktree's locations. A source in the main checkout resolves exactly as before, and `layout.test_dirs` mirror roots were already worktree-anchored. No configuration change is needed (reported as issue #74).
