# N326 - tests that depend on UNRELEASED/ holding content

## Classification of tests that read the live tree

Found by scanning tests/ for `unreleased` and `PENDING_RELEASE_NOTES` (24 files).

Read the live tree and pass on README-only scaffolding (fine):

- tests/integration/test_config_migrations_integration.py (skips when no manifest is staged)
- tests/integration/test_pending_release_notes_holding_area.py (parametrised over callouts, empty set skips)
- tests/integration/test_upgrade_task_schema.py, tests/integration/test_post_upgrade_tasks_are_reachable.py (released guides keep `there_are_tasks_to_check` true)
- tests/unit/scripts/test_branch_install_gate_is_unadvertised.py (globs callouts, empty passes)
- tests/unit/install/test_relay_timeout_cap_migration_advisory.py (manifest is in the released config-changes dir)

Build their own staging (fixture, not the live tree): tests/acceptance/test_guarded_branch_install.py (fixed in 3f0311e8e),
tests/integration/test_upgrade_pre_deploy_phase_runs_on_layer1.py, and the unit tests that write UNRELEASED under tmp_path.

Defects found beyond the two already fixed: none.

## Defence chosen

Option (a), a dynamic run: `tests/integration/test_suite_passes_on_a_released_unreleased_tree.py` clones the repo
(keeping the release tags the upgrade tests install from), overlays the working tree, deletes every non-README file
under `CLAUDE/UPGRADES/UNRELEASED/`, commits, and runs every test file that mentions the holding area inside it.
The file list is found by scanning, so a new reader is covered without being listed.

Why not (b), a static scan: the legitimate readers (lints over whatever is staged) and the defective ones read the
tree the same way. Only running them on the released state tells them apart.

Why this shape: it mirrors `test_qa_walkers_examine_files_from_any_checkout.py` (copy the tree, run from the copy).
It is marked `slow`: it includes the upgrade and install end-to-end tests, which are where the original defect hid,
because they clone the repo.

## Proof

A deliberately added probe test asserting a staged callout exists in the live tree passed in the normal suite and made
the new test fail, naming `tests/unit/test_tmp_n326_probe.py::test_probe`. The probe was then removed.

## Decisions and hazards met

- A plain tracked-file copy was not enough: the install tests need release tags and `uv.lock`, so the copy is a clone.
- The QA resolver needs a venv under the copy's `untracked/`: the running interpreter's `sys.prefix` is linked in.
- No PYTHONPATH: it leaked into the upgrades the tests launch and shadowed the code they install (two layer1 tests
  failed on it). The copy's `src` goes on the runner's own `sys.path` only.
- Only the Status line of N326 was changed in the ledger.
