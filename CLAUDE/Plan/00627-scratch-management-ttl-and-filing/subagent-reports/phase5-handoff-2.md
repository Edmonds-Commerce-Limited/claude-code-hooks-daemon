# Phase 5 handoff 2 (Task 5.2 done; Task 5.1 partly done)

## Done

- `src/claude_code_hooks_daemon/core/scratch_inventory.py`: `Inventory`/`InventoryEntry`/`InventoryArchive`, `inventory_from_report` (built from the sweep report, no second walk; session children named `<session>/<name>`; a torn store marks it incomplete), `write_inventory` (temp file and rename), `read_inventory` (missing or malformed is a `problem`, never raised), `inventory_caps` (wires `scratch_caps.evaluate_caps` with the recorded level as `previous`), `refresh_inventory`, `refresh_in_background` (one at a time, guarded by a module lock; failures logged). Tests: `tests/unit/core/test_scratch_inventory.py`.
- `daemon/cli.py`: `_record_scratch_inventory` after `scratch-sweep --apply` (project root only, not `--root`); `start_scratch_inventory_refresh(repo)` for SessionStart.
- `handlers/session_start/scratch_sweep.py`: `render_inventory_report` (counts by verdict, overdue-to-file with filing command, archives expiring within 48h with restore command, caps at warn or above), silent when clean, speaks when missing/unreadable/incomplete/stale (24h). `handle` appends it and starts the background refresh. `get_claude_md` updated. Tests: `tests/unit/handlers/session_start/test_scratch_sweep_report.py`.

## Decisions to review

- **A dry run does not write the inventory.** DESIGN.md section 8 says "every `scratch-sweep` run", but `tests/unit/daemon/test_cli_scratch_sweep.py::TestReadOnly` and `test_cli_scratch_apply.py::TestDryRunNeverCreatesTheStore` contract the dry run as changing no inode. Only `--apply` refreshes. Either amend DESIGN.md or relax that contract.
- Priority stays `SCRATCH_SWEEP = 56`, equal to `BRANCH_SWEEP`. Not verified that the tie orders `scratch_sweep` after `branch_sweep`; check the registry's tie-break, or set it to a value between 56 and 57.
- The counts cover the scratch root (and its session directories) only. The archive store and the registered stores are not counted yet (DESIGN.md section 8 says they should be).

## Remaining for Task 5.1

- Refresh after a Bash command that creates directories under a scratch root: a PostToolUse trigger calling `start_scratch_inventory_refresh`. Task 5.4's `R-SCRATCH-CAP` needs the same "creates a directory tree" detector, so build them together.
- Existing `test_scratch_sweep.py` handler tests now run the real `_start_refresh` (a background classify of their tmp project). They pass, but an autouse fixture patching `module._start_refresh` would be cleaner.
- No acceptance test was added for the report (the existing one still matches).
