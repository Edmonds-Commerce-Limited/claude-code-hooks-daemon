# Plan 00505 report: issue #74, declared test_path_map anchors at the worktree

## Cause

`_map_declared_test_paths` resolved the workspace against `resolve_project_root()` (the main checkout) and passed that same root to `path_matches_globs`. For a source under `<root>/untracked/worktrees/<name>/`, the workspace root was the main checkout, so flat and mirrored candidates landed under the main checkout.

The glob match was also wrong, which the brief asked me to verify. A test with `apps/app/src/**` failed before the fix: the glob is project-relative, so the worktree source was `untracked/worktrees/<name>/apps/app/src/...` and never matched. An unanchored `src/**` still matched, which is why a main-checkout test could wrongly satisfy a worktree source.

## Fix (tdd_enforcement.py)

- Coordinator review round: the first version relied on `enclosing_checkout`, which only knows `untracked/worktrees/` and `.claude/worktrees/`, so the issue's own `untracked/scratch/wt` stayed anchored at the main checkout. A new function `nested_git_checkout_root` in `core/worktree_paths.py` now returns the nearest ancestor below the project root with a `.git` entry (file for a linked worktree, directory for a nested clone). `enclosing_checkout` and its other callers are untouched. It is unit-tested in `tests/unit/core/test_worktree_paths.py`, and a handler test reproduces the issue literally: a real worktree at `untracked/scratch/wt`, a mirrored `tests/Small` mapping, and the test committed in the worktree. The write is allowed, and the deny names the worktree path when the test is removed. 223 passed across the two test files.
- `_checkout_root_for` takes `nested_git_checkout_root` first, then falls back to `enclosing_checkout`, then to the project root. For a main-checkout source it returns the project root unchanged, so those sources resolve as before.
- `path_matches_globs` now gets the checkout root as `project_root`.
- `_workspace_anchor` resolves the workspace through the registry against the project-root equivalent of the source, then re-roots it at the checkout (`<worktree>/<workspace-rel>`). Declared sub-projects (`apps/api`) therefore anchor correctly inside a worktree. Flat and mirror both use it.

## `_map_layout_mirror_paths`

It has no such defect. It anchors on the source path segments before `src`, as the inferred resolvers do. I added a test pinning that and made no code change there.

## Tests (tests/unit/handlers/test_tdd_enforcement.py, `TestDeclaredTestPathMapAnchorsAtTheWorktree`)

The tests use a real `git worktree add` in `tmp_path`.

- Flat and mirrored worktree tests allow the write.
- The deny names the worktree paths, not the main checkout's.
- A main-checkout test does not satisfy a worktree source.
- A main-checkout source is unchanged.
- An anchored glob matches inside the worktree.
- A declared project inside a worktree keeps its workspace anchor.
- Layout mirror roots (pin only).

RED run: 6 failed (right reasons), 2 passed (the main-checkout and layout pins). GREEN run: the whole file passes, and with test_worktree_paths.py 217 passed. black (py311), ruff and mypy on the touched source are clean.

## Other changes

- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/027-tdd-test-path-map-anchors-at-the-worktree.md`.
- PLAN.md Tasks 1.1-1.3 ticked.
