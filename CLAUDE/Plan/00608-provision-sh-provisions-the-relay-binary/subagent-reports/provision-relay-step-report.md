# Plan 00608 report: provision.sh provisions the relay binary

Branch: `agent-a85cf266bd3c1c30d-57f43a44` (pushed; not merged, no release).

## What changed

- `provision.sh` (root file; `.claude/provision.sh` is a symlink to it, so there is one source and nothing to sync): runs the clone's own `scripts/install/relay_provision.sh` (`provision_relay_binary`, which also regenerates the forwarders) in a child shell.
  - Fresh checkout: after the venv build, before the daemon start deadline is set.
  - Clone at the expected version: after the venv is current or repaired, only when `relay_deploy --check` says the binary is missing or defective. A CLI without `--check` (older release) is provisioned.
  - Sync: after the switch, outside every rollback path, for the new tag.
  - Warn, never abort: the banner prints, a closing warning names `hooks-daemon transport on`, exit stays 0. A clone without `relay_provision.sh` skips with a note.
  - `--background`: never builds or downloads; reports a missing relay and names `transport on`.
  - `relay_enabled: false`: nothing done (the CLI returns early; `--check` exits 0).
- `relay_deploy.py`: new read-only `--check` (0 disabled or usable, 3 missing or defective; `--version-tag` not required with it).
- Tracked-file honesty: regenerating forwarders can rewrite tracked `.claude/hooks/*`. The closing lines now say so when it happens, and only claim "No tracked file was changed" when it did not.
- Release note 078, PLAN.md filled in, journal entry for the repair investigation.

## Tests

- `tests/unit/install/test_relay_deploy.py`: 71 passed (6 new for `--check`).
- `tests/integration/test_provision_sh.py`: 92 passed (21 new; the sandbox stub answers relay_deploy and forwarder_generator and logs calls, so nothing builds or downloads).
- No real-CLI provision run in the sandbox (stand-in used); the real CLI is covered by the unit tests.

## QA (`llm_qa.py changed --base origin/main`, using `HOOKS_DAEMON_VENV_PATH=/workspace/.venv` because the worktree has no venv)

40/43 passed. Remaining: `format` (black auto-fixed one test file mid-run; committed, `black --check` is now clean on all four touched Python files), project_handlers NOT MEANINGFUL (detector failed: format, same cause), and `changed_tests` 1171 passed, 0 failed, with one unmapped file that fails the run: `src/claude_code_hooks_daemon/install/relay_deploy.py [too-broad]`. Reported, not suppressed; needs `--allow-unmapped` or a map rule from the coordinator.

## Relay repair leaving no state (separate question)

Not reproduced; no code change. Journal: `JOURNAL/2026-11-15/213141Z-finding-6d9f78.md`. `start_relay_repair` writes its state file before spawning, so no state file means the handler never reached it on that box (SessionStart not delivered to that daemon, uninitialised project context, or a daemon with a different project root). The status WARNING comes from a different code path. Open question for the box: did SessionStart reach the daemon, and under which root?
