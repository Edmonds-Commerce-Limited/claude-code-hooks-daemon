# N271 report: uv trusted locations and `--uv`

Branch `worktree-n271-uv-locations`, implementation commit `7ca6882b9`.

## Design

- `scripts/install/venv.sh`: `_venv_uv` resolves, in order, `VENV_UV_OVERRIDE`
  (the `--uv` path), `command -v uv` (Layer 2's trusted PATH), then
  `_venv_uv_search_dirs`: `$PIPX_BIN_DIR` (absolute only), `~/.local/bin`,
  `/opt/homebrew/bin`, `/usr/local/bin`, `/home/linuxbrew/.linuxbrew/bin`.
  Every directory except `~/.local/bin` (searched as before) must pass
  `_venv_uv_dir_is_trusted`: owned by root or the running user, not group- or
  world-writable. The existing root-only `_gate_dir_is_trusted` would reject a
  user-owned Homebrew prefix, so it is not reused. `VENV_UV_OVERRIDE` is
  cleared when venv.sh is sourced, so an inherited variable never counts. The
  not-found error names both fixes.
- `scripts/upgrade.sh` (Layer 1): parses `--uv PATH` / `--uv=PATH`, requires an
  absolute path to an executable file (exit 1 with a message otherwise), and
  passes it to Layer 2 as `--uv <path>` in argv, never in the environment.
  `PIPX_BIN_DIR` is added to the `env -i` kept-names list so it survives the
  reset. `--help` documents the flag.
- `scripts/upgrade_version.sh` (Layer 2): `_take_uv_override "${@:4}"` validates
  again (`fail_fast`) and sets `VENV_UV_OVERRIDE`. The second-pass re-exec
  forwards `"${@:4}"`, so the override survives it. The one-shot handoff file
  is unchanged.
- No config key anywhere (owner ruling).
- `TestLayer2NeverRunsAUvOnlyTheCallerPathNames` still passes: the caller's
  PATH is never searched.

## Guard (`upgrade_approval_guard`, R-UPGRADE-APPROVAL-ENV-BYPASS)

- `PIPX_BIN_DIR` added to `_UPGRADE_STEERING_VARS`, so every spelling the
  guard already catches (assignment, `export`, `env`, `read`, ...) is denied on
  an upgrade command.
- New `_UV_OVERRIDE_ARG_RE` matches `--uv` / `--uv=`; a segment carrying it
  makes the command "steered", so it is denied when it runs an upgrade by name,
  by content, or as an unreadable script with upgrade arguments.
- Rule text, verbose text and `get_claude_md` mention `--uv`.
- Not denied: `PIPX_BIN_DIR=... pipx install uv`, `uv --version`, `--uv` on a
  non-upgrade command, or `--uv` inside `echo`/`grep`.

## TDD red evidence

Guard tests (`TestUvLocationSteering`), before the guard change:

```
FAILED ...test_denies_uv_argument_on_an_upgrade[bash scripts/upgrade.sh --project-root . --uv /tmp/evil/uv]
AssertionError: bash scripts/upgrade.sh --project-root . --uv /tmp/evil/uv
assert False is True   (1 failed, 178 deselected, run with -x)
```

Shell tests (`tests/integration/test_uv_trusted_locations.py`), before the
script changes: `19 failed, 6 passed`. The failures covered pipx dir, search
dirs, override, not-found message, Layer 1 argument validation, `--help`, and
`PIPX_BIN_DIR` in the kept names. After the changes all pass (28 tests in that
file after a test-design change from handoff carrying to argv carrying).

## QA

- `test_upgrade_approval_guard.py` + `test_uv_trusted_locations.py` +
  `test_layer2_env_sanitisation.py`: 245 passed.
- shellcheck `-x -S warning` on the three scripts: clean. black, ruff clean on
  touched files. mypy on the new test file and the handler is clean; five
  pre-existing `union-attr` errors remain in older tests of
  `test_upgrade_approval_guard.py` (lines 111, 185, 215, 249, 808 before
  edits), not touched here.
- `llm_qa.py changed --base main --allow-unmapped` (after a 3500 s wait on the
  host-wide lock): 24/28 passed. The 4 failures are in files this branch does
  not touch: `format` (black auto-fixed `tests/integration/test_ci_job_timeouts.py`),
  `error_hiding` (`daemon/server.py` `_peer_pid`, `utils/cron_hosts.py`
  `hostname_override_of_process`), `input_contract` (`hooks_daemon_hostname`).
  Its `changed_tests` step recorded 0 tests and reported the tree as changed
  during the run (the auto-format), so it certifies nothing.
- The 74 test files it selected were then run directly with the worktree
  venv's pytest: exit 0, no failures (the only skips are acceptance tests that
  need a live daemon). The exact pass count was not captured (the run used
  `-q -q`).

## Unverified

- No run on a real macOS Homebrew prefix or a real pipx install; the trust
  check is exercised with temp directories and modes only.
- The auto-format edit to `tests/integration/test_ci_job_timeouts.py` by the QA
  run is left uncommitted in the worktree; it is not part of this change.
