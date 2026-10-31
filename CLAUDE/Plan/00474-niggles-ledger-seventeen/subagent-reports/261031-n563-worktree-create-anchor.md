# N563 report: WorktreeCreate anchors to the main checkout

## Red

Added `TestLinkedWorktreeCwd` (real git, tmp_path, a linked worktree, a seed entry present only in the
main checkout, cwd inside the linked worktree and inside a subdirectory of it). Both tests failed before
the fix: `WorktreeSeedError` for the seed case, and the worktree path nested under
`<linked>/.claude/worktrees/` for the subdirectory case.

## Fix

- `GitRepo.main_worktree_root()` (`utils/git_repo.py`): reads `git worktree list --porcelain` through the
  existing `parse_worktree_porcelain` and returns the first record (git lists the main checkout first).
  Falls back to `root` when the listing is unavailable.
- `WorktreeCreateHandler._repo_root` returns `repo.main_worktree_root()`; the fallback-to-cwd path when no
  repo resolves is unchanged.
- Unit tests in `tests/unit/utils/test_git_repo.py::TestMainWorktreeRoot` (main, linked, unreadable).

## Other callers

- `worktree_path()` only joins a given root; it has no anchoring logic of its own. Its one caller is the
  create handler, now fixed.
- `WorktreeRemoveHandler` takes the worktree path from the payload and uses `cwd` only as the directory to
  run `git worktree remove` / `prune` from. Git resolves the shared repository from inside a linked
  worktree, so the same defect does not apply. No change.

## Verification

- `tests/unit/handlers/worktree_create`, `tests/unit/utils/test_git_repo.py`, worktree_remove and core
  worktree tests: 337 passed.
- `llm_qa.py lint type_check format`: 3/3 passed.
- The worktree had no venv; `uv sync --frozen --all-extras` built `.venv` (gitignored) and
  `HOOKS_DAEMON_VENV_PATH` pointed llm_qa at it.
