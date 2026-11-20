## 16:07 · decision · — — R7a: a standalone repository in scratch is DISPOSABLE (coordinator applying the owner)

Coordinator's ruling (R7a), applying the owner's typed decision "no special rules for repos ... scratch repo ... no value" (DESIGN.md section 0): a STANDALONE repository in scratch (no remote, no shared history with this project, not a worktree of it) is DISPOSABLE once its TTL has passed. There is no archive-and-hold (UNCERTAIN) path for it; DISPOSABLE still means packed, verified and held for the short retention (R5 stands).

Built as proof P7 in `core/scratch_verdict.py`: `RepoFindings.standalone_roots` (each standalone repository's work tree, plus its git directory when that lies outside the work tree) and `other_roots` (every other repository root). A path is covered by P7 when the deepest repository root holding it is a standalone one, so a clean pushed clone nested inside a standalone repository keeps its own rule, and a file beside the repository (`e/report.md` next to `e/tmp/repo/.git`) is judged on its own.

Unchanged, as safety rather than special rules for scratch repositories: registered worktree and outside-pointing `.git` (PROTECTED), related clone failing R6 (PROTECTED), in-progress git operation and any unjudgeable repository (STUCK), a held tracked file (PROTECTED), and REFERENCED once Task 2.4 lands.

Surface for the security review: a `git init` in scratch now turns its subtree into short-hold content.
