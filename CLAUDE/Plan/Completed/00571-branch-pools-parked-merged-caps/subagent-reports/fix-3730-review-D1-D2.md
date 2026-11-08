# v3.73.0 review fixes D1 and D2

Branch `fix-3730-review`, from `origin/release/3.73.0`.

## D1: worktree ownership path normalisation

- `core/agent_ownership.py`: `canonical_path()` resolves a record against the project root and
  strips trailing separators and symlinks. `running_holds(untracked, project_root=None)` stores
  canonical worktree holds; `ownership_refusal` compares the canonical form of git's path.
- Callers pass the repo root (`branch_cleanup.py`, `cmd_worktree_reap`).
- Tests: `tests/unit/core/test_agent_ownership.py::TestWorktreePathNormalisation`. The relative,
  trailing-slash and symlink cases failed first (3 failed, 9 passed); the absolute and
  different-worktree cases passed before and after.

## D2: N585, reap branch deletion

- `core/worktree_reaping.py::prune_branch` deletes through `branch_safety.delete_branches`
  (containment against the base, recovery bundle under `untracked/deleted-branches/`).
  `PruneOutcome.kept` marks a merged branch that was not deleted. `run_fn` was dropped from
  `prune_branch` (it no longer runs git itself).
- `cmd_worktree_reap` prints `KEPT` for such a branch, counts it toward the non-zero exit, and
  turns an unclassifiable `CalledProcessError` into a logged `KEPT`.
- Tests: `tests/unit/daemon/test_cli_worktree_reap_merged_unpushed.py` (real repo and remote).
  Before the fix, the merged-unpushed test failed with the branch kept and exit 0, and the
  kept-reporting test failed on the missing `delete_branches` seam. Older fake-git tests were
  moved to a fake `delete_branches`.
- Ledger: N585 marked fixed in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`.

## QA

`llm_qa.py changed --allow-unmapped`: every check passed except one `changed_tests` failure,
`tests/unit/test_doc_write_jail.py::TestSessionWiring::test_every_checkout_of_the_repository_is_protected`,
which passes when run alone (environmental, concurrent checkouts). Two findings from that run
(bandit B404, error_hiding silent-fallback) were fixed, then `error_hiding format lint security type_check` re-ran 5/5 PASSED.
