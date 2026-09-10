# Pyright sweep — supervise test batch (manual_model_choice, model_switch_signal, audit_banner, futile_model_restore, attributed_downgrade)

Files touched:

- `tests/unit/supervise/_load.py` — added `SupervisorTickOutcome` and `SupervisorStateMachine` Protocol classes (structural types for `TickOutcome`/`CompactStateMachine` instances produced by the `importlib`-loaded module).
- `tests/unit/supervise/test_attributed_downgrade.py`
- `tests/unit/supervise/test_audit_banner.py`
- `tests/unit/supervise/test_futile_model_restore.py`
- `tests/unit/supervise/test_manual_model_choice.py`
- `tests/unit/supervise/test_model_switch_signal.py`
- `tests/unit/supervise/conftest.py` — read only, 0 diagnostics, no change needed.

Fix applied: helper functions/fixtures that previously returned `object` (or took `machine: object`) now return/accept the two Protocols from `_load.py`, imported under `TYPE_CHECKING`. Signatures changed: `_machine`, `_decide`, `_drive_fable_to_opus`, `_open_episode_and_fire_restore`, `_flush`, `_tick`, `_escape_episode`, `_AuditDriver.tick`. No test bodies or runtime logic changed.

Before: 127 pyright errors across the 5 test files (all `reportAttributeAccessIssue` on `object`).
After: 0 errors, 0 warnings across all 7 files in the batch.

pytest: 107 passed (the 5 files), `-q -p no:cacheprovider`.
ruff check: all checks passed.
black --check: all 7 files unchanged (one file needed one re-wrap of two long signatures, applied).

Nothing left unfixed; no real bugs found in the tests themselves — all diagnostics were the known "loaded-via-importlib module is `Any`, but a helper's own `-> object` annotation walls it back off" shape described in the brief's cookbook.
