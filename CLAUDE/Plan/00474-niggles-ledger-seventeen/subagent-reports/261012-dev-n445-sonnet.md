# N445 (#97): restore dropped opt-in handlers before the upgrade restarts the daemon

Branch `worktree-issue-97-restore-early`. One commit (see `git log`), message ends `Addresses #97`.

## Change

- `scripts/upgrade_version.sh` (Layer 2): new `run_effective_handler_restore`, beside `run_config_compatibility_check`. It runs `check-effective-handlers --apply` with the target venv (`$VENV_PYTHON`), `--from ${CURRENT_VERSION#v}` (the pre-upgrade version Layer 2 already holds, handed over by Layer 1 as `HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION`), `--to` `_target_release`, and `$TARGET_CONFIG`. Called once on the already-at-target branch and once on the full path (Step 7), each right after `run_config_compatibility_check`, so after `verify_venv` and before the first deploy and the restart. The command is written once.
- Failure handling: exit 0 nothing; exit 1 prints the report; exit 2 (target without `--apply`) prints an info line; any other exit prints the output plus a warning. None aborts the upgrade. An unknown previous version or missing config skips it.
- `_read_handoff` now records `HANDOFF_DIR` (only for a genuine handoff).
- `scripts/upgrade.sh` (Layer 1): reads `$_HANDOFF_DIR/restored-handlers` and merges it with its own `--apply` call. RESTART THE DAEMON is printed only when Layer 1's own call restored something (`_eff_restored_here`). When only the Layer 2 file restored, it prints an info line that the handlers were written before the restart, and the summary says "restored ... before the daemon restarted". The metadata awk still sees the RESTORED / STOP / START lines.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/046-the-upgrade-restores-opt-in-handlers-before-it-restarts-the-daemon.md` (Audience: client projects).

## Step 2 choice

Layer 2 writes the restored-handler report (only when it contains `handler(s) RESTORED`, and only under a genuine Layer 1) to `restored-handlers` in the handoff directory Layer 1 already creates and removes on exit; Layer 1 reads it. Layer 1 keeps its own `--apply` call, which after the early restore finds nothing left to restore and still reports stops and starts. An older Layer 2 writes no file, so Layer 1 behaves exactly as before (applies, then asks for the restart). An environment variable could not carry this: Layer 2 is started with an allow-listed environment.

## Tests

New `tests/integration/test_upgrade_restores_handlers_before_restart.py` (14 tests). Ordering is a structural assertion on the script text (like `test_upgrade_pre_deploy_phase_placement`) for both routes; the Layer 2 function and the Layer 1 block are also executed, extracted from the scripts, against a stub interpreter (hand-off, exit 2, crash, unknown version, direct call, Layer 1 restart message, older Layer 2, target without `--apply`).

- Red first: 12 failed, 2 passed (the 2 are the older-Layer-2 and target-without-`--apply` tests, which pin the unchanged behaviour). After the change: 14 passed.
- Existing tests changed: none. No existing test pinned the old ordering or the RESTART message (checked `tests/integration/test_upgrade_sh_effective_handler_report.py`, `test_upgrade_pre_deploy_phase_placement.py`, `tests/unit/daemon/test_cli_check_effective_handlers.py`; all pass unchanged).

## QA (targeted, worktree venv)

- `bash -n` on `scripts/upgrade.sh` and `scripts/upgrade_version.sh`: clean.
- pytest: the new file, plus the upgrade integration tests, `tests/unit/scripts`, `test_cli_check_effective_handlers`, the holding-area and release-slate tests: all passed (616 and 111 passed in two batches).
- `./scripts/qa/llm_qa.py changed`: 37/40 passed; format failed on the new test file (black), fixed with black directly, then the format, lint, type_check, pyright and shell_check detectors re-run: 5/5 passed (format 0 files, lint, type_check, pyright, shell_check all clean). `changed_tests` and `project_handlers` were marked not meaningful in that run only because the format detector failed; their 952 and 238 tests passed.

## Deviations

None from the ruling. No daemon restart, no push, no merge, no real upgrade run.
