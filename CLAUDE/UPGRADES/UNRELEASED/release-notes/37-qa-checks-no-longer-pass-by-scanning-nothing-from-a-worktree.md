# Callout: QA checks no longer pass by scanning nothing from a worktree

**Plan**: 00466
**Audience**: handler authors

Ledger entry N26. This affects contributors to this repository, and anyone
who runs its QA from a git worktree.

Three QA checks, `skill_refs`, `doc_truth` and `github_urls`, skipped any
file whose absolute path contained a directory name they exclude, such as
`untracked` or `worktrees`. Run from a worktree under `untracked/worktrees/`,
they skipped every file, scanned nothing, and reported a pass. `magic_values`
did the same with `constants`, `fixtures` and `test`: a checkout under such a
directory skipped all of `src/` or treated every file as a test.

Each check now judges directory names only below the tree it scans. When a
check had files to examine and examined none, it now fails and says so. A
checkout's location can no longer produce a pass.

An integration test runs every tree-walking check from a copy of the tree
placed under a path made of those directory names. It fails when any check
examines nothing, and every `scripts/qa/check_*.py` must be listed in it as a
walker or a fixed-input check.
