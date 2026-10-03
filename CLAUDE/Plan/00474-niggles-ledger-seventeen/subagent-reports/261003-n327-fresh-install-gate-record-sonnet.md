# N327: fresh install leaves no gated-install record

## Root cause

- Receipt written: `src/claude_code_hooks_daemon/install/upgrade_gate.py` `record_gated_install` (line 399), called only from `main` (line 959) on a PROCEED with a target stamp.
- Receipt read: `gated_install_stamp` (line 424), used by `evaluate_gate` line 611-628: stamp == target and no matching receipt gives an unknown-range report (exit 3, owner approval, every guide since v2.0).
- `scripts/install_version.sh` stamps the venv through `ensure_venv` and never runs the gate, so a fresh install has the stamp and no receipt.

## Which copy of the gate runs

`scripts/upgrade.sh` (fetched from main by the shim) checks the target tag out into the client's daemon dir and then runs `$DAEMON_DIR/scripts/upgrade_version.sh`, whose `run_pre_deploy_phase` runs `$DAEMON_DIR/src/.../upgrade_gate_standalone.py`: the TARGET tag's copy. A main-only fix never changes a v3.68.0 install's behaviour. Install likewise runs the tag's `install_version.sh`.

## Real-world impact

- Affected: a v3.68.0 install with no receipt (every fresh install of v3.68.0) that re-runs the upgrade to the SAME v3.68.0.
- Not affected: an upgrade to any other release (stamp differs from target; normal range path; the stamp is a trusted FROM; the PROCEED records the receipt, which heals the install). An install that upgraded INTO v3.68.0 through the gate has the receipt.
- A patch release helps only new installs; existing ones heal on the next upgrade or by the owner's `hooks-daemon approve-upgrade`.

## Decision

The owner gate for a stamp-equals-target install with no receipt stays. It exists (Plan 00376 fresh review MAJOR 1) because checkout plus `hooks-daemon repair` can manufacture that equality and land a MAJOR without approval. Missing receipt cannot be told from that, so it is not weakened.

## Fix

- `upgrade_gate.record_install_main` and the `record-install` subcommand of `upgrade_gate_standalone.py` write the same receipt.
- `scripts/install_version.sh` reads any prior venv stamp before `ensure_venv` (`PRIOR_VENV_STAMP`) and calls `record-install` after the venv is verified, only when there was none.
- Tests: `tests/unit/install/test_upgrade_gate.py::TestRecordInstall`, `tests/unit/install/test_upgrade_gate_standalone.py::TestRecordInstallWithoutVenv`, `tests/integration/test_install_records_gated_install.py` (placement pins).
- Acceptance: `tests/acceptance/conftest.py::create_daemon_clone` tags the throwaway clone's HEAD as the next patch when the newest published tag's installer lacks `record-install`; the four acceptance tests then run the fixed code. Once a release carries the fix the real tag is used.
