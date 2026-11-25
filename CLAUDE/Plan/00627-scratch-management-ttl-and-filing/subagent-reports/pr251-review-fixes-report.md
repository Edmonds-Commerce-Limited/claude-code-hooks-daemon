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

## `llm_qa.py changed` result

Run at tip `e9e676179` (after the host QA lock freed), with `FULL_QA_LOCK_WAIT_SECONDS=3300 HOOKS_DAEMON_VENV_PATH=/workspace/untracked/venv-workspace-py313-ee75a947 PYTHONPATH=<worktree>/src`. Earlier attempts failed to start (no venv for the worktree, then a 600s lock timeout).

**QA: 42/43 PASSED, 1/43 FAILED.** The single failure is `changed_tests`: 1744 passed, 0 failed, 5 skipped across 46 test files, with 10 unmapped changed files. Every unmapped file has reason `too-broad`, not `uncovered`: their tests through `daemon/cli.py` reach 40 or more test files, so the run says the coordinator's full gate covers them. The ten files:

- `core/scratch_archive.py`, `scratch_archive_apply.py`, `scratch_archive_claim.py`, `scratch_archive_facts.py`, `scratch_archive_pack.py`
- `core/scratch_liveness.py`, `scratch_repos.py`, `scratch_sweep.py`, `worktree_reaping.py`
- `daemon/cli.py`

Because of those ten, the `changed_tests` step cannot pass without `--allow-unmapped`. I did not pass it. Everything else is green, including magic_values (0 violations), format, lint, type_check, pyright, docs_qa and plan_qa (advisories only, 0 blocking), and sensitive_content. The run also printed one warning: `install_mode_marker` was "NOT RECORDED FOR THIS TREE" because the working tree changed during its run (its own result was 0 violations). The two timeout literals that failed PR 251's earlier CI are fixed by PR 256, now merged here, and `magic_values` is clean.
