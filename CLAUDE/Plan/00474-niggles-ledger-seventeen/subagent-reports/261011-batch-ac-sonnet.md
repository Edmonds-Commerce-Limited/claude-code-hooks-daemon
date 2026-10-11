# Batch AC report: N246 residual, N369, N357

## N246: update-index and apply --cached in the staging simulation

- `utils/git_commit_parsing.py`: `StagingRun.subcommand`; `STAGING_SUBCOMMANDS` = add, update-index, apply;
  `ADD_TOKEN`, `UPDATE_INDEX_TOKEN`, `APPLY_TOKEN` public.
- `utils/staging_simulation.py`: `update-index` runs against the scratch index with a flag whitelist
  (`--add --remove --force-remove --replace --verbose -q`); `apply` runs only with `--cached`/`--index`, runs the real
  `git apply --cached` on the scratch index, and on a failed apply stages the paths named by the patch's `---`/`+++`
  headers (from the repo root). Unreadable patch, unknown flag, failure: the existing policy (add of every change).
  `UnreadablePatchError` plus `log_and_continue` keep the error-hiding audit clean.
- `plan_qa/command_journal.py`: only `git add` covers a journal (`ADD_TOKEN` check).
- Finding: `git apply --cached` run from a subdirectory ignores patch paths outside it, so the simulation matches git.
- Shared simulation per dispatch: a performance note only (a timing-out add costs up to 5s per gate); verdicts are correct
  per gate. Not changed.

## N369: forwarder test fails in a harness worktree

- Reproduced (1 failed, 12 passed). Cause: `scripts/bootstrap-self-install.sh` baked the checkout's absolute path into
  `.claude/hooks-daemon.env`; harness worktrees symlink that file. Fixed the script to write `"$PROJECT_PATH"` (as
  `install.py` and `setup_worktree.sh` do). Test now skips with the remedy when the env file pins another checkout.
- Not done: this container's `/workspace/.claude/hooks-daemon.env` still has the literal (outside the worktree). Until it
  is rewritten, the test skips in worktrees. `.claude/ccy/` and settings.json untouched.

## N357: map rule

- `scripts/qa/changed_tests_map.yaml`: `handlers/pre_tool_use/*.py` and `utils/git_commit_parsing.py` select
  `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py`. Pinned by
  `tests/unit/qa/test_performance_test_is_wired.py`.

## Results

- 9653 passed, 2 skipped (one is the N369 skip, one a permissions skip) over `tests/unit/utils`, targeted `tests/unit/qa`,
  `tests/unit/plan_qa`, the six commit-gate handler tests, the ordinary-command corpus gate, the forwarder and
  worktree-env integration tests; 1 failed.
- The failure: `test_safety_handlers_hostile_input_performance.py::...[nesting]`, "PipBreakSystemHandler cost grew 43x for
  8x input", reproduced twice. The branch changes nothing that handler reads (no use of the staging or journal modules);
  I could not run a baseline (the editable-install guard refuses a foreign src). Coordinator to confirm on main.
- An earlier combined run showed 23 `test_llm_qa_main_moved.py` and 2 `test_llm_qa_venv_resolution.py` failures; both
  files pass when run alone, so they depend on run conditions in this worktree.
- black, ruff, mypy (utils, plan_qa): clean. pyright: only unresolved `pydantic`/`mdformat` imports in unrelated files.
  `shellcheck -x scripts/bootstrap-self-install.sh`: clean.
