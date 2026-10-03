# N324: CI-run lookup names the run it read

Branch worktree-n324-ci-run-lookup. Code under `_gh_ci_lookup` in `src/claude_code_hooks_daemon/daemon/cli.py` and `CiRunState` in `src/claude_code_hooks_daemon/core/release_slate.py`.

## Selection rule

Runs for HEAD's sha are walked newest first. The first run that is completed, not cancelled or skipped, and carries an executed matrix job decides. Green means every matrix job succeeded. A newer failed matrix run therefore beats an older green one (fail closed). Still-running, cancelled and tier-only runs are passed over. With no qualifying run, the newest run of the sha stands in and is not green; no run at all stays `None`.

## Output

`CiRunState.run_id` is new, and `describe()` appends `(run <id>)`, so the slate report names the run.

## Tests

- `tests/unit/daemon/test_cli_release_slate_check.py`: run naming, newest full-matrix run wins, cancelled plus re-run (both orders), in-progress newer beside completed older, no qualifying run, failed matrix and failed tier runs. `gh` is faked at the existing `subprocess.run` seam.
- `tests/unit/core/test_release_slate.py`: `carries_matrix_jobs`, `describe()` run id.
- The old test "a failed run is not asked for its jobs" was replaced: a failed run is now inspected, because it may be the newest matrix evidence.

## QA

`llm_qa.py changed --allow-unmapped`: 37/37 passed at 47495137c. `--allow-unmapped` was needed because `release_slate.py` and `cli.py` are "too-broad" for the changed-tests map. `canonical_callers` fails when the worktree has no `untracked/scratch/`; creating it fixed that.
