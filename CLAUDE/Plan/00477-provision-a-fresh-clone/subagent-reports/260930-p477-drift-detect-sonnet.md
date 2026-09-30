# Plan 00477 Task 5.1 (drift detection) and N277: report

## Where this was done

The brief named the worktree `untracked/worktrees/worktree-p477-drift-detect`. This agent was isolated in `.claude/worktrees/agent-a46150631d146fb17-f42a99e1` (branch `agent-a46150631d146fb17-f42a99e1`, same base `9c9429a96`), and the harness refused any git command that changed into the named one. All work is in the isolated worktree. The branch is pushed to the requested remote name with `git push -u origin agent-a46150631d146fb17-f42a99e1:worktree-p477-drift-detect`. The local branch name differs; the coordinator merges from the remote branch or from the commit hashes below.

## Commits

1. `9f5426f84` N277: `_resolve_python_cmd` returns the resolver's failure status.
2. The Task 5.1 commit follows it (hash in the coordinator summary).

## N277

- Cause: `if PYTHON_CMD="$(resolve_venv_python ...)"; then return 0; fi; local rv=$?`. An `if` with no `else` whose condition fails leaves `$?` at 0.
- Test first: `tests/integration/test_init_sh_resolve_python_cmd_status.py`. The canonical library is present and its resolver returns 7. Red before the fix (`rc=0 python_cmd=[]` where `rc=7` was expected, 1 failed, 2 passed), green after (3 passed; the neighbouring resolver and latency tests, 32 in all, pass).
- Fix: the status is taken from the assignment (`PYTHON_CMD=... || rv=$?`), then returned.
- Caller audit: `validate_venv` already captured the status explicitly. `_hooks_daemon_run_cli_helper` used `! _resolve_python_cmd`, which previously fell through and ran an empty interpreter and now returns 1 as intended. `provision.sh` judges `PYTHON_CMD` as well as the status; it stays correct, and only its comment (which described the bug) was corrected.

## Does the Plan 00386 path already cover part of Task 5.1?

Yes, and it was extended rather than paralleled. `_detect_stale_clone` compared the installed clone's `version.py` with the tracked `.claude/HOOKS-DAEMON.md` header, and `emit_hook_error` has a VERSION_MISMATCH branch that names both versions and whether the clone is behind or ahead. What it lacked:

- It never looked at `daemon.expected_version`, so a pull that changed the key but not the header was invisible.
- It is reached only after a failed start (`ensure_daemon`'s diagnosis), so a clone stale enough to start and run was not reported at all.
- A clone ahead of the header was told "regenerate the tracked assets", which is wrong when the project deliberately named an older version (a downgrade).

So `_detect_stale_clone` now compares the clone with `_resolve_expected_version` (the key, else the header; an invalid key falls back to the header exactly as before the key existed), and the message has a config-sourced variant with UPGRADE and DOWNGRADE wording. The header-sourced message is unchanged. The running-daemon gap is covered at SessionStart by extending the existing `version_check` handler instead of adding a handler: it already runs on SessionStart, already has a local-only early return (the Plan 00291 branch-install advisory) ahead of the cache and network, and already carries the version comparison.

## Design

- `init.sh`: the drift check stays on the failure path only. `ensure_daemon` returns before any diagnosis when the daemon answers, so a healthy hook pays nothing (a test makes both the detector and the resolver fail loudly if the running path reaches them, and another shows a successful start never reaches them). A daemon that starts fine on the wrong version is the running-daemon case, reported by the SessionStart handler.
- Self-install (daemon root equals project path) never reports drift.
- `version_check`: `_drift_context()` reads the running `__version__` and the tracked key fresh from `.claude/hooks-daemon.yaml` (not the config the daemon loaded at start, which is the stale side of the comparison). It runs before the cache and network, so a drift notice never mentions "latest". A resumed session matches only when drift exists: a pull between sessions is when drift appears, and a resume is how that session comes back. A branch install keeps its own advisory; no key, an invalid key, unreadable config, and an uninitialised project context are silent (unparseable YAML is logged at warning).
- `install/expected_version.py`: new `read_expected_version(path)`, the Python twin of the bash resolver's config step. Missing file, absent key or a value that is not strict X.Y.Z answer None; invalid YAML raises `ValueError` (fail fast; the handler catches and logs).
- The message names the installed version, the expected version and its source, UPGRADE or DOWNGRADE, that a restart cannot fix it, that nothing was changed, and the command: `/hooks-daemon upgrade X.Y.Z (Skill tool: skill=hooks-daemon, args=upgrade X.Y.Z)`. That is the form `SKILL.md` documents. A downgrade asks the reader to confirm it is intended, since it can come from a commit made on an older checkout.

## Measured cost

Host load average was about 20 during measurement, so absolute numbers are noisy. Timed with `EPOCHREALTIME`, 300 calls of `_detect_stale_clone` in a client-shaped fixture (script: `untracked/scratch/measure_drift.sh`, not committed), three runs each:

| shape                | before (HEAD)   | after           |
| -------------------- | --------------- | --------------- |
| no key, no drift     | 17.6 to 26.7 ms | 19.2 to 22.0 ms |
| key present, equal   | 16.7 to 17.8 ms | 17.4 to 21.4 ms |
| key present, drifted | 15.9 to 18.8 ms | 18.7 to 21.0 ms |

Roughly 1 to 3 ms more per call, inside the noise. It is paid only on the failed-start diagnosis path. The hot path (daemon running) gained no code. A trace test pins that, with the key absent and no drift, the detector runs exactly one external process (the `grep` of the clone's `version.py`, as before), with no `awk`. With the key present one `awk` runs, through the existing `_config_daemon_key_raw`.

The SessionStart handler adds one small YAML read per SessionStart (and per resumed SessionStart), not per hook.

## Tests

- Red before the implementation: 14 failed and 17 passed across `test_init_sh_version_drift.py` and `test_version_check_drift.py`, plus an ImportError for `read_expected_version`. Green after.
- Run by path, all passing (425 tests): `tests/integration/test_init_sh_version_drift.py`, `test_init_sh_stale_clone_version.py`, `test_init_sh_expected_version.py`, `test_init_sh_needs_provision.py`, `test_init_sh_resolve_python_cmd_status.py`, `test_init_sh_pretooluse_fail_closed.py`, `test_init_sh_venv_missing_message.py`, `tests/unit/install/test_expected_version_reader.py`, `tests/unit/install/test_expected_version.py`, `tests/unit/handlers/session_start/test_version_check_drift.py`, `test_version_check.py`, `test_version_check_branch_install.py`; plus `test_init_sh_venv_resolution.py` and `test_venv_resolver_hot_path_latency.py` for N277.
- Static: ruff, black `--target-version py311`, mypy and pyright (with `--pythonpath .venv/bin/python`) on every touched Python file, shellcheck `-x` on `init.sh` and `provision.sh`, `scripts/qa/audit_error_hiding.py` (it caught a `return None` on an `except` in the first reader; reworked to raise) and `scripts/qa/check_input_contract.py`, all clean. No suppressions or allowlist entries were added.

## Not verified

- The `llm_qa.py changed --base main --allow-unmapped` run did not happen. The first attempt found no fingerprint-keyed venv in this worktree (the isolated worktree has only a `uv sync` `.venv`, on Python 3.14). The second, with `HOOKS_DAEMON_VENV_PATH` pointing at that `.venv`, queued on the host-wide QA lock held by pid 2217140 (another agent's worktree) and gave up after the full 600 s wait. It was not re-queued. The targeted checks listed above stand in for it; the coordinator's own QA run covers the rest.
- Tests ran on Python 3.14 (the worktree's `uv sync` venv), not the project's 3.11 venv.
- That `upgrade <older version>` completes end to end for a real downgrade: `scripts/upgrade.sh` and `LLM-UPDATE.md` refer to downgrades, but no downgrade was run.
- The live SessionStart wire path (daemon to Claude Code) for the new advisory. The unit tests cover the handler, and the SessionStart formatter sends context on both `systemMessage` and `additionalContext`, but no real session was started.
- The other `provision.sh` or `init.sh` consumers of `_HOOKS_DAEMON_TRACKED_VERSION` were checked by reading only (it now holds the expected version, whatever named it).
- Task 5.2 (sync) and 5.3 (approval-gate question) were not touched: nothing here moves the daemon.
