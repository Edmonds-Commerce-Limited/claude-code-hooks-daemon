# r371 relay-repair review fixes (D1, D2, N1, N2)

Worktree `untracked/worktrees/worktree-r371-relay-repair`, branch
`worktree-r371-relay-repair`, base `df6c44a3b`. Source findings:
`untracked/agent-reports/auto/261023-164904-code-reviewer-ab3907968ed931ed8.md`.

## D1: a relay repair whose child dies early reads "running" forever

- **Real?** Yes. Reproduced with my own probe (`untracked/scratch/r371rr/probe_d1d2.py`):
  a `spawn_fn` that runs `/bin/false` left `status=running` with no pid, and
  `read_state_file` returned `RUNNING, pid None`.
- **Tests (RED first):**
  - `tests/unit/install/test_relay_repair.py`:
    - `TestStartRelayRepair::test_the_spawned_pid_is_recorded_at_once`
    - `::test_a_result_the_child_already_recorded_is_not_overwritten`
    - `::test_a_child_that_dies_before_recording_its_pid_reads_as_failed`
    - `::test_a_pid_that_cannot_be_recorded_is_reported_with_the_start`
  - `tests/unit/install/test_background_sync.py`:
    - `TestAPidlessRunningRecord::test_a_fresh_one_is_still_running`
    - `::test_one_older_than_the_grace_is_a_failure`
- **Fix:**
  - `src/claude_code_hooks_daemon/install/relay_repair.py`:
    - `start_relay_repair` keeps the pid `spawn_fn` returns and calls
      `_record_spawned_pid` (~line 232).
    - `_record_spawned_pid` (~137) is a compare-and-swap. It rewrites the
      state only while it still holds the exact claim text, so a child that
      already wrote its own record or result is never put back to running.
    - The swap runs under a short `state.lock` (`_STATE_LOCK_NAME`, ~61).
      Every `_write_state` (~121) now takes that lock too.
    - If the pid cannot be recorded (an OSError), the notice carries `failure`,
      so the session-start warning shows it to the user.
  - `src/claude_code_hooks_daemon/install/background_sync.py`:
    - `read_state_file` (~122) turns a pid-less RUNNING record into FAILED
      once its mtime is older than `PIDLESS_RUNNING_GRACE_SECONDS = 60` (~42).
    - `provision.sh` always writes `pid=$$` (provision.sh:923), so only a
      relay-repair claim is ever pid-less.
- **Side effect:** the fake spawners in `test_relay_repair.py` and
  `tests/unit/handlers/session_start/test_relay_binary_checker.py` now return
  `os.getpid()` instead of 4242. The pid is recorded now, and a dead one reads
  as failed.

## D2: the repair child is never reaped, so it becomes a zombie that looks alive

- **Real?** Yes. In the same probe, `/proc/<pid>/stat` showed `Z`, and
  `_process_alive` returned True. After the fix the probe shows the child gone
  (reaped) and the record `failed`.
- **Tests:**
  - `tests/unit/install/test_relay_repair.py`:
    - `TestSpawnDetached::test_the_child_is_reaped_when_it_exits`
    - `::test_runs_in_its_own_session_with_output_in_the_log` was rewritten.
      It no longer calls `waitpid` itself, which had hidden the defect.
  - `tests/unit/install/test_background_sync.py`:
    `TestRunningIsCheckedAgainstTheProcess::test_a_zombie_pid_is_a_failure`
- **Fix:**
  - `relay_repair.py`:
    - `spawn_detached` (~158) starts a daemon thread running `_reap` (~149,
      `os.waitpid`). It logs the exit code.
    - An unexpected `ChildProcessError` raises in that thread and goes to the
      excepthook rather than being swallowed. Nothing in `src/` sets SIGCHLD.
  - `background_sync.py`: `_process_alive` (~167) treats a zombie as dead
    (`_is_zombie`, ~170, reads the state letter after the last `)` in
    `/proc/<pid>/stat`). This also covers any other unreaped child.

## N1: `WorkerChildPid` ignores its injected `proc_root` on the learned-pid branch

- **Real?** Yes. Line 1680 called `cached_own_session_ids(self._pid)` with no
  `proc_root`. The new test failed against a fake `/proc`.
- **Test:** `tests/unit/supervise/test_session_identity.py`:
  `TestWorkerChildPid::test_a_learned_pid_is_resolved_under_the_injected_proc_root`
- **Fix:** `.claude/ccy/claude-supervise.py:1680` now passes `self._proc_root`.
  The live supervisor process was not touched.

## N2: the failure banner always says "missing or not executable"

- **Real?** Yes. The headline was hard-coded.
- **Tests:** `tests/unit/install/test_relay_deploy.py`, class `TestProvisionRelayForInstall`:
  - `test_the_banner_names_the_actual_defect_of_a_present_executable`
    (an executable Git LFS pointer)
  - `test_a_failed_route_over_a_usable_binary_claims_no_defect`
  - an added assertion in `test_enabled_without_source_and_without_binary_fails_naming_fix`
- **Fix:** `src/claude_code_hooks_daemon/install/relay_deploy.py:532`
  (`_failure_banner`):
  - The headline is "its binary is {relay_binary_defect(binary)}: {path}".
  - If the file is usable after a failed route (an old binary left in place),
    it reads "could not be provisioned".

## QA

- Targeted unit run of `tests/unit/install/`, the relay checker and
  `test_session_identity`: all passed.
- First `llm_qa.py changed` run:
  `QA: 38/41 PASSED, 1/41 FAILED, 2/41 NOT MEANINGFUL (detector failed: error_hiding)`.
  It flagged `_reap` swallowing `ChildProcessError` and the pid-record OSError
  being only logged. Both were fixed in commit `0134f11cf`, with no suppressions
  and no exclusions.
- Final run on `0134f11cf`
  (`llm_qa.py changed --range df6c44a3b..HEAD --allow-unmapped`, full output in
  `untracked/scratch/qa-r371-rr.txt`): `QA: 41/41 PASSED`.
- `claude-supervise.py` and `relay_deploy.py` were left unmapped
  (too-broad), so the coordinator's full gate must cover them.
- The commit after `0134f11cf` adds only this report.
