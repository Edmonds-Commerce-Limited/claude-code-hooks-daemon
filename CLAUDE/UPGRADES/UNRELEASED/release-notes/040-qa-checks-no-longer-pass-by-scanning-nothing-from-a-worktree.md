# Callout: QA checks no longer pass by scanning nothing from a worktree

**Plan**: 00466
**Audience**: handler authors

Ledger entry N26. This affects contributors to this repository, and anyone
who runs its QA from a git worktree.

Four QA checks, `skill_refs`, `doc_truth`, `github_urls` and `shell_audit`, skipped any
file whose absolute path contained a directory name they exclude, such as
`untracked` or `worktrees`. Run from a worktree under `untracked/worktrees/`,
they skipped every file, scanned nothing, and reported a pass. `magic_values`
did the same with `constants`, `fixtures` and `test`: a checkout under such a
directory skipped all of `src/` or treated every file as a test.

Each check now judges directory names only below the tree it scans. A
checkout's location can no longer produce a pass.

A check that examined nothing now fails and says why. That covers three cases:
its exclusions dropped every file, its scan root is missing, or the root is
empty. Every tree-walking check follows this rule. `check_git_history` now
fails on a `--repo` that is not a git repository instead of passing. A
`--path`/`--root` scan of a directory with nothing to check is a failure, not
a clean result.

Tree-walking checks also no longer read inside `.git` or inside a nested
repository, such as a worktree, submodule or clone below the scanned tree.
Before, a `--path` scan by `check_sensitive_content` reported a term found in a
commit message under `.git`.

Integration tests pin the class. They run every tree-walking check from three
places: a copy of the tree placed under a path made of the excluded names, a
checkout holding only the QA scripts, and a missing or empty root. A check
must examine something or fail. Every `scripts/qa/check_*.py` and `audit_*.py`
must be listed there as a walker or a fixed-input check.
