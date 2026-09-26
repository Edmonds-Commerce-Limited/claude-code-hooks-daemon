# Ledger 00466 lifecycle batch: N67, N69, N70

**Agent**: Opus 5.5 (fixer). **Worktree**: `worktree-n466-lifecycle`, from
main `fe14348e7`. **Gate**: not queued, per the brief (a review follows).

## Commits

| Commit      | Entry         | What                                                                      |
| ----------- | ------------- | ------------------------------------------------------------------------- |
| `19db5bb1f` | N67           | The daemon-down recovery exemption judges the launcher it runs (note 150) |
| `422a84bb4` | N69           | Transport deny reasons say whether the daemon was reached (note 151)      |
| `a0b318316` | N70           | `stop` falls back and cleans up only when proven safe (note 152)          |
| `ae2343f10` | N67 follow-up | The `init.sh` realpath guard test judges the shell binary, not `os.path`  |
| (this one)  | ledger        | This report, and new niggle N126                                          |

N67, N69 and N70 are marked ✅ Remedied in `NIGGLES.md` and `PLAN.md`, each
with its own "Remedied" paragraph.

## N67: the recovery carve-out judges the resolved launcher

- `init.sh` now has one shared python3 source, `_HOOKS_DAEMON_RECOVERY_PY`,
  that both carve-out checks run: `emit_hook_error`'s (through
  `_hooks_daemon_stdin_is_recovery_command`) and `send_request_stdin`'s.
  Before this, the two were separate copies.
- A call is exempt only when its whole command is exactly a launcher
  spelling plus a subcommand, AND
  `realpath(cwd/<spelling>) == realpath(<PROJECT_PATH>/<spelling>)`, AND
  that path is a regular file.
  - `cwd` is the hook input's `cwd`; `PROJECT_PATH` is passed as argv.
  - A missing, relative or non-string `cwd` denies. So does a project with
    no launcher, a directory in the launcher's place, or an unresolvable
    path (`OSError`/`ValueError`).
  - A symlink to the real launcher is exempt, because `bin/hooks-daemon`
    anchors to its own real location.
- Every deny text now says "from the project root, run exactly …".
- Tests:
  - `TestRecoveryCarveOutJudgesTheResolvedLauncher` (14 cases);
  - a planted-launcher test on the `emit_hook_error` path, in both
    `test_emit_hook_error_jqless.py` and `test_ci_passthrough.py`;
  - every existing recovery test now supplies `cwd` and a real launcher.
- RED: against `HEAD`'s `init.sh` in a `git archive` copy, 14 tests fail.
- The follow-up commit fixes a detector, not the site.
  `test_init_sh_realpath_portability.py` flagged any `realpath` word, which
  included the embedded `os.path.realpath`. It now matches the shell binary
  only, and a parametrised test pins that.

## N69: deny messages name the real cause

- **`emit_error_json`'s verb.** N24 fix8 had already removed "reached" for
  `socket_not_found`/`connection_refused`, but it chose the verb by
  `error_type`, so two cases were still wrong:

  - an unclassified error raised after `connect()` (an undecodable response)
    said "unreachable";
  - a full accept backlog (the kernel refused the connect) said "reached".

  The verb now comes from a `daemon_reached` flag, set right after
  `sock.connect()` returns.

- **Unclassified PreToolUse context.** An unclassified PreToolUse failure
  carried the fail-open context ("safety handlers are inactive", "Skill
  tool"), which is the same misnaming as R4-MA2. It now gets "could not
  connect at all" (before connect) or "the exchange with the daemon failed"
  (after connect). The five copies of the restart advice are one
  `_RESTART_ADVICE` list.

- **Relay.** The new `describe()` prints a `WouldBlock`/`TimedOut` error as
  "timed out". It is used for the socket read and write failures.

- **Tests.**

  - `TestDenyReasonNamesWhatHappened` (6 cases). Three fail at `HEAD`. The
    other three pin fix8's verbs and fail when a `git archive` copy's verb
    is mutated back to "reached".
  - `test_relay_pretooluse_timeout_deny_names_the_timeout` in
    `test_relay_guard_fail_open.py`, RED against the old binary. I added the
    same assertion to the manual `relay/test_relay.py` (13/13 pass).

## N70: pidfd fallback and cleanup only when proven safe

- `_open_pidfd` returns `None`, which means "fall back to signalling by
  number", only in two cases: `os.pidfd_open` is missing, or it fails with
  ENOSYS, EMFILE or ENFILE (`_PIDFD_UNAVAILABLE_ERRNOS`).
  - ESRCH is re-raised. `cmd_stop` then prints "exited before it could be
    pinned; nothing to stop" and returns 0. It sends no signal, runs no
    proof and deletes no file.
  - Any other errno makes `cmd_stop` refuse to signal (exit 1).
- If the first SIGTERM finds the proven process gone, `cmd_stop` returns 0
  and leaves the PID file and socket alone. A merely stale PID file never
  gets that far, because `read_pid_file` clears it.
- Test changes:
  - The `_reject_unproven_real_signals` fixture now presents `_UNREAL_PID`
    as an unsupported platform, so the by-number tests still drive their
    own `os.kill` patch.
  - I added the fixture to `TestCmdStopSignalsOnlyThisProjectsDaemon`,
    which had no guard. Without it, those tests reached the real
    `os.pidfd_open`.
  - New class `TestCmdStopFallsBackAndCleansUpOnlyWhenProvenSafe`, plus
    `_open_pidfd` errno tests.
  - `test_stop_process_not_found` now expects no cleanup.
- RED: 7 tests fail against `HEAD`'s `cli.py`.
- N59 safety:
  - Every signal in a test goes to `_UNREAL_PID` through a patched
    `os.kill`/`signal.pidfd_send_signal`, or to the test's own `Popen`
    child (signal 0 through its pidfd).
  - No `killpg` anywhere.
  - Each live `bin/hooks-daemon restart` of this worktree's daemon ran the
    new `cmd_stop` through the pidfd path and succeeded.

## Verification

- **Targeted tests, per entry**: green. Before the last commit I ran every
  test file that references `init.sh`, plus `test_cli_commands.py`: 1486
  passed, 11 skipped, 0 failed.
- **Linters**: ruff, black, mypy and pyright are clean on every touched
  Python file. `shellcheck -x init.sh` is clean. The relay builds with
  `-D warnings`.
- **Daemon**: restarted after each `src`/`init.sh` commit and reported
  `RUNNING`.
- **Worktree setup**: the worktree had no venv.
  - I built one with `bin/hooks-daemon repair`, then synced the dev extras
    from `uv.lock` (`uv sync --frozen --all-extras`, as
    `scripts/setup_worktree.sh` does).
  - I provisioned `.claude/hooks-daemon.env` through
    `install.create_daemon_env`.
  - I built the relay with `relay/build.sh`.
  - Before the lock sync and the env file were in place, three unrelated
    tests failed (ruff 0.16 findings in `claude-supervise.py`, and two
    forwarder tests with no env file). They fail the same way on a
    `git archive` of main in that environment. With the standard setup
    they pass.

## For the reviewer

- **N68** (owner decision) is unchanged. N67 edited `emit_hook_error`, the
  function that holds the NOT_INSTALLED branch. That branch still returns
  before the carve-out check and still fails open.
- **New niggle N126**: the relay's PreToolUse deny has no recovery
  carve-out. With a daemon that accepts but never answers, the relay denies
  `bin/hooks-daemon restart` itself, even though its own deny text says to
  run it. The relay is live in the dogfood config. Candidate remedies are
  in the entry. I chose N126 because 111-118, 120, 122 and 123 are already
  taken on other branches. Renumber it if that clashes.
- **Check-to-run window (N67)**: the launcher is judged at PreToolUse time
  and run afterwards. While the daemon is down every other tool call is
  denied, so only a process that is already running could swap the file in
  between. This is the same boundary class as N71.
- **Exported function**: `_hooks_daemon_stdin_is_recovery_command` is
  exported, but its source variable is not (shellcheck SC2089/SC2090). A
  child shell that has not sourced `init.sh` gets an empty source,
  `python3` exits non-zero, and the call is denied, which fails closed.
