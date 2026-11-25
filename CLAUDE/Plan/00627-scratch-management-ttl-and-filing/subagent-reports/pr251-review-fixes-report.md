# PR 251 review fixes: report

Branch `plan-00635-host-seat-lane-guard`. The merge of `origin/main` (PR 256) was clean, with no conflicts.

## Findings

- **S1 confirmed.** Two tests failed on the old code: an intact tree claimed under a fresh id with an old adopted record of the entry, and a new folder sharing the name of a deleted adopted entry. Both returned `stuck`. The adopt-STUCK branch of `resume_claimed` is removed and both now return `renamed-back`. The strict test `test_a_claim_naming_another_archive_than_the_adopted_one_is_stuck` is replaced by the two tests: its scenario cannot occur, because removal only runs after proof against the claim's own archive, and nothing in `src/` calls `adopt()`. The DESIGN.md adopt row, release note 106 and the plan-journal entry are updated. Niggle N737 in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md` records that the adopt claim-id binding must be enforced where adoption is wired (it also folds in review nit N2).
- **S2 confirmed.** The new gate test (an entry holding a `user.*` xattr) returned no blockers before the fix. `worktree_scratch_evacuation.py` now calls `refuse_unrestorable`, so the whole worktree is refused before anything is packed. The foreign-owner gate test now patches that name.
- **S3 fixed.** The `resume_claimed` docstring is rewrapped and now matches the code.
- **Nit N1 done.** The xattr refusal message and probe docstring name `/proc`. Nit N3 (naming the DESIGN row instead of review labels in comments) was not done.

## Verification run

Run with `PYTHONPATH=<worktree>/src` and the python at `/workspace/untracked/venv-workspace-py313-ee75a947/bin/python`, from the worktree. Without `PYTHONPATH` the source-tree guard refuses to start, because the venv's editable install points at main's `src/`.

- `python -m pytest -p no:cacheprovider --no-cov tests/unit/core/test_scratch_archive_remove.py tests/unit/core/test_worktree_scratch_evacuation.py tests/unit/core/test_scratch_archive_pack.py tests/unit/core/test_scratch_archive_claim.py tests/unit/core/test_scratch_archive_apply.py`: 296 passed, 3 skipped, 0 failed. I did not look up which 3 tests were skipped.
- Red-first runs: the two S1 tests failed on the old code (2 failed). The evacuation file gave 2 failed, 24 passed, the failures being the new xattr test and the foreign-owner test, which patched a name the module did not yet have.
- `black`: unchanged on the 6 touched Python files. `ruff check`: all checks passed. `mypy`: no issues in the 6 files.

## Not done: `llm_qa.py changed`

It did NOT run to completion, so there is no QA summary to report and no `changed_tests` mapping result. Three attempts failed to run:

1. No `HOOKS_DAEMON_VENV_PATH` set, so the interpreter could not be resolved (the worktree has no venv). This is an environment problem and not a code result.
2. The same, with `HOOKS_DAEMON_PYTHON` only.
3. With `HOOKS_DAEMON_VENV_PATH` set, it waited 600s on the host-wide QA lock held by another agent's worktree (pid 291216) and then exited without starting.

A fourth run, with `FULL_QA_LOCK_WAIT_SECONDS=3300`, was queued behind that lock when this report was written. Its output file is `untracked/scratch/qa2.txt` in this worktree. PR 251's earlier CI QA failure came from two literals fixed in PR 256 (now merged here), but no run has confirmed that.
