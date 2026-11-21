# Task 3.4 report: bulk cleanup is dry-run first, batched and resumable

Branch: `plan-00594-task-3-4-bulk-cleanup`. PLAN.md checkbox untouched.

## Design (smallest honest fit)

- Before: `branch-sweep --clean` deleted at once (`--dry-run` previewed). It had no preview by default, so the contract changed as the task allows: `--clean` alone is now the dry run, and a new `--apply` deletes. `--apply` with `--dry-run` is a usage error; `--apply` without `--clean` is a usage error. Every daemon-printed one-step command (`sweep_clean_command`) now ends in `--apply`.
- Dry run prints every branch with its proof: `would delete <name> (proven <tier>)` and `would delete remote <remote>/<name> (tip <sha12>, proven merged into <default>)`, then `Apply with: <command>`. It deletes nothing and writes no bundle.
- Batched: `BULK_BATCH_SIZE = 50` in `core/branch_cleanup.py`. A batch is up to 50 branches (local and remote together); one recovery bundle per batch is written before its local deletions, and one `git push --delete` (leases per ref, `_push_deletes` unchanged) per batch. Remote deletes still use `prove_remote_merged` unchanged.
- Resumable with no plan file: the repository is the only state. A deleted branch is no longer a candidate, a branch gone since the scan is skipped as `<name>: already deleted`, and the loop stops cleanly on `KeyboardInterrupt` or a failed batch (`CalledProcessError`, `TimeoutExpired`, `OSError`). The report carries `bundles`, `remaining`, `stopped` and `next_command`; `render` prints `Stopped:`, `Remaining N ...` and `Resume with: <command>`. A refused push or refused delete lists the leftovers in `remaining` too. Worktree removal moved from the scan loop into each batch, just before that batch's bundle.
- Not adopted from DESIGN.md section 2.6: a plan JSON file plus `--apply <plan> --batch N`. A recomputed plan cannot go stale and needs no state file; say if you want the file form.

## Defect found and fixed while building the fixture

`clean_sweep` built its inventory on the hook-sized budget (`branches.sweep.budget_ms`, 3000 ms). On a repository with a few hundred branches the budget ran out before keep notes were read, so a branch kept with `branch-keep` looked unkept and was DELETED by `--clean`. `clean_sweep` now uses `BULK_SWEEP_BUDGET_MS = 600_000`. Regression test: `test_a_spent_hook_budget_never_hides_a_keep_from_the_sweep` in `tests/unit/core/test_branch_cleanup_keeps.py`.

## Tests (written first, each seen failing before the code)

- `tests/unit/core/test_branch_cleanup_bulk.py`: real repo plus bare remote built with `git fast-import`, 325 branches (75 merged incl. 2 kept, 250 unmerged incl. 2 parked). Seen failing first: ImportError on `BULK_BATCH_SIZE`. Covers dry run deletes nothing and lists proofs and the apply command; full run deletes exactly the 73 proven-merged ones locally and remotely, keeps unmerged/kept/parked, uses 2 bundles, every deleted branch is in a bundle, a second run does nothing; SIGINT at batch 2 then resume ends in the uninterrupted final state; a failed batch stops and reports remaining; a pre-receive-refused push plus a branch deleted mid-run resume to the same final state.
- `tests/unit/daemon/test_cli_branch_sweep.py`: seen 5 failures first (preview default, `--apply`, usage errors, parse).
- `test_branch_cleanup_keeps.py` regression test: seen failing first (kept branch deleted under a starved budget).
- Two existing assertions updated for the new strings (`test_branch_cleanup.py` sweep line now has `--apply`; `test_branch_cleanup_remote.py` dry-run remote line now carries the proof).
- Bulk file runtime: about 35-40 s on a loaded host (each full sweep of 75 branches costs roughly 6-9 s because `classify_branch` runs about 12 git calls per branch, twice); over the 30 s target. Shrinking further would stop it being a several-hundred-branch fixture; the per-branch classification cost is the real limit.

## Verification

Neighbour suites run as separate invocations: core, daemon, scripts, session_start, pre_tool_use, post_tool_use, and the three integration files all pass apart from the known artefacts (two in `test_paths_diagnose_venv_start.py`, one child-pytest failure in pre_tool_use). `run_autofix.sh` run; `llm_qa.py format lint type_check error_hiding magic_values semgrep plan_qa docs_qa` all green after fixing one error_hiding finding (the batch-failure handler now logs).

## Other

Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/047-branch-sweep-clean-previews-then-applies-in-batches.md`. Not changed: the hand-written `branch-sweep --clean` mentions in `cleanup_after_merge` guidance and `branch_creation_guard` fix text (they still read as the command family; the generated CLAUDE.md block is derived from that text), and `housekeeping.md` row 21 (its own `--apply` is the housekeeping skill's).
