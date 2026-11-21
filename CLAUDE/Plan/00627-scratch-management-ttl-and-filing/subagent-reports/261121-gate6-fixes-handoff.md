# Gate 6 fixes handoff

Branch `agent-acff915e4bf3b86e6-0a26f829`, both fixes pushed.

## 1. mypy `[misc]` "Cannot infer type of lambda" (cli.py)

Commit `1f7279aba`. The `recheck=lambda asked_state=state: reread(asked_state)[1]`
in `cmd_worktree_reap` is replaced by a local typed factory
`recheck_of(asked_state: WorktreeState) -> Callable[[], str | None]`, called as
`recheck=recheck_of(state)`. Binding is still per-iteration.

Verified: `mypy src/claude_code_hooks_daemon/daemon/cli.py` clean;
`scripts/qa/run_pyright_check.py --json` 0 errors; black and ruff clean;
error-hiding audit clean; project semgrep rules: 0 results.

## 2. Root-conditioned skip in test_worktree_evacuate_blockers.py

Commit `7683fd618`. `test_foreign_owner` no longer uses `chown` or
`skipif(os.geteuid() != 0)`. A helper `_walk_reporting_owner` wraps
`walk_tree` as seen by `worktree_scratch_evacuation` (the gate that calls
`refuse_foreign_owner`) and reports `sub/b.txt` with uid 4242, the same pattern
as `tests/unit/core/test_scratch_archive_pack.py`.

Mutation check: with `refuse_foreign_owner`'s uid comparison disabled, the test
fails ("the question was asked"); restored, it passes.

Tests run: `tests/integration/test_no_root_conditioned_skips.py`,
`tests/unit/daemon/test_worktree_evacuate_blockers.py`,
`tests/unit/daemon/test_worktree_evacuate.py` all pass; the worktree-reap CLI
and core reap tests (96) pass. Runner was root; the test no longer depends on
euid. Black, ruff, pyright, semgrep test rules clean.

Note: mypy on test files (outside the gate's mypy scope) reports two
pre-existing errors in `tests/unit/daemon/test_worktree_evacuate.py` (lines 32
and 867, including another default-arg lambda); not touched here.
