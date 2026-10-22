# Plan 00529 Task 2c: implementation report, part 4 (detached session-start repair)

This part continues `261022-task-2c-impl-3-opus.md`. It covers step 2 of that handoff only. Head: `a153ce94d`,
pushed.

## Step 2: detached repair, once per cause (commit `a153ce94d`)

- New module `src/claude_code_hooks_daemon/install/relay_repair.py`:
  - `start_relay_repair(...)` claims one state file per cause under `<untracked>/relay-repair/`. The file is keyed
    by `cause_key(binary, defect, daemon version)` and created with `O_EXCL`, so a cause is attempted at most once
    across sessions. It then spawns `python -m claude_code_hooks_daemon.install.relay_repair` detached and never
    waits for it. An `OSError` while creating the claim or spawning is returned as `failure` and recorded as
    `failed`, never raised into the hook.
  - `spawn_detached` uses `os.posix_spawn(..., setsid=True)`: stdin is `/dev/null`, and stdout and stderr go to
    the cause's log. There is no shell, no PATH search and no `subprocess` import, so there is no bandit finding and
    no `nosec`.
  - `run_relay_repair` (the child) records `running` with its own pid. It then takes `fcntl.flock` on
    `relay-repair/repair.lock`, which is blocking, so two repairs never build at once. Inside the lock it:
    - re-checks the binary; one that is already usable is recorded `synced` and nothing is built;
    - runs `ensure_relay_binary` and then `regenerate_deployed_hooks` (the `transport on` routine without the toggle,
      restart or probes);
    - re-checks the binary. A provisioning failure, a binary that is still unusable, or an exception is recorded as
      `failed` with its reason. An exception is also logged and re-raised.
  - The state uses `background_sync`'s `key=value` format. `read_sync_record` now delegates to a new shared
    `read_state_file(path, logs)` (DRY).
- `relay_binary_checker` keeps its WARNING line and adds a second line:
  - "Relay repair started in the background (log: ...); if the next session still warns, run: ... transport on";
  - or "running";
  - or "FAILED: <detail> (log ...)", with "not retried automatically; run transport on, or delete <state> to
    retry", shown at every session start;
  - or "recorded success, yet the binary is unusable again";
  - or "<spawn failure>. Run: transport on".
- The spawn is injectable (`handler.spawn_repair`). The new autouse fixture `no_relay_repair_builds` in
  `tests/conftest.py` makes the checker's default spawn raise under pytest. Without it, any test that runs the
  SessionStart handlers against this checkout would start a real build, because the relay is enabled and
  `untracked/bin/` is absent here.

### Red, then green

- `tests/unit/install/test_relay_repair.py`, with the module absent: `ImportError: cannot import name 'relay_repair' from 'claude_code_hooks_daemon.install'` (collection error).
- `tests/unit/handlers/session_start/test_relay_binary_checker.py`, with the new tests and the checker unchanged:
  `6 failed, 12 passed`. The failures were the acceptance description, start-detached, not-started-twice,
  spawn-failure-reported, failed-repair-reported-every-session, and recorded-success-yet-unusable.
- Green: 99 passed across `test_relay_binary_checker.py`, `test_relay_repair.py`, `test_background_sync.py` and
  `test_version_check.py`.
  - The spawn test is real: `posix_spawn` of `sys.executable` asserts a new session, empty stdin, and stdout and
    stderr both in the log.
  - The lock test holds the lock in the test and asserts that provisioning waits for it.
- mypy is clean on the three source files and bandit reports "No issues identified". ruff is clean after one
  import-sort fix. `run_autofix.sh` was applied before the commit.

### Known limits

- The daemon never reaps the detached child, so it stays a zombie until the daemon exits. The child writes its own
  final status, so this matters only if the child is killed hard. In that case `os.kill(pid, 0)` still sees the
  zombie, and the record reads `running` until the daemon restarts.
- Forwarders rewritten by the repair are not followed by a daemon restart or probe, unlike `transport on`. The
  binary alone engages the relay at the next hook.

## What is left

1. Step 3 of the part-3 handoff: docs and release note.
   - Docs: `CLAUDE/Worktree.md` around lines 108-121 and the transport docs. State that a missing or broken relay
     never changes a verdict, that every answer says so until `transport on`, and that session start repairs it in
     the background once per cause. Also record the PermissionRequest finding from part 3.
   - Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/019-<slug>.md`. Re-check main for 017, 018 and 019
     before you pick the number.
2. Tick Task 2c in PLAN.md once steps 1 to 3 are all delivered.
3. Run targeted QA once:
   `FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range origin/main..HEAD --allow-unmapped`.
   Commit any autofixes.
4. The coordinator's full gate must also cover the 8 unmapped files listed in part 3, plus `tests/conftest.py`.
