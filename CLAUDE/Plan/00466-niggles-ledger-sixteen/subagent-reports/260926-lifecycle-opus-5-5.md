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

## N126: the relay hands a failed PreToolUse exchange to the one carve-out

Assigned by team-lead after the first report. The fix is committed with this
report update.

- **Mechanism.**
  - The relay keeps every request byte it pumps. On a PreToolUse
    mid-exchange failure (timeout, I/O, oversize or empty response) with a
    `--fallback`, `judge_via_fallback` finishes reading stdin. It then runs
    `/bin/bash <forwarder> --no-relay` with the whole request replayed on
    stdin and `HOOKS_DAEMON_RELAY_FAILED=<class>: <detail>`.
  - `init.sh` captures and unsets that variable at source time, so a daemon
    the hook starts never inherits it.
  - `send_request_stdin` then skips the nc rung and the socket, and calls
    `fail('relay_exchange_failed', …)` with `daemon_reached = True`.
    `emit_error_json` denies through the N67 carve-out, which resolves the
    launcher and fails closed.
  - The relay never parses the request and holds no second copy of the
    carve-out.
- **Fail-closed hand-off.** If stdin cannot be completed, or the forwarder
  cannot be spawned, exits non-zero or writes nothing, the relay writes its
  own deny, as before. With no `--fallback` the relay also denies as before.
  Setting the variable by hand can only turn a call into a deny.
- **Scope of the exemption.** It is exactly N67's set: the project's own
  launcher with `restart`, `status`, `logs`, `stop` or `start`. `repair` is
  not in that set. The brief said "restart or repair", but widening the set
  would be a separate decision.
- **Latency.** A wedged daemon costs one relay budget, not two: the
  hand-off never contacts the daemon again.
- **Tests.**
  - `TestRelayMidExchangeFailureIsJudgedByTheOneCarveOut` (6 cases): the
    real relay binary against a wedged `pre-tool-use.sock`, with a real
    forwarder and `init.sh`. It covers the project's own restart, a planted
    launcher, an ordinary call, a silent fallback, a failing fallback and a
    1 MiB request replayed byte for byte.
  - `TestARelayHandOffIsJudgedWithoutAskingTheDaemonAgain` (5 cases): the
    `init.sh` side.
  - RED: 7 of these fail against `HEAD`'s `init.sh` and a relay built from
    `HEAD`'s source. Both fail-closed hand-off tests fail when a scratch
    relay's answer check is mutated away.
  - I marked the new payloads `synthetic_source`
    (`test_live_probes_are_marked`).
- **Verification.** Every test file that references `init.sh`, plus the
  relay tests: 1493 passed. The one failure in that run was the unmarked
  probe, now fixed; its file and the probe check then passed 41/41.
  `relay/test_relay.py` passed 13/13. shellcheck, ruff, black, mypy and
  pyright are clean, and the relay builds with `-D warnings`.
- **Deploy.** The dogfood relay binary (`/workspace/untracked/bin/hooks-relay`)
  must be rebuilt or redeployed after merge for this to take effect.

## For the reviewer

- **N68** (owner decision) is unchanged. N67 edited `emit_hook_error`, the
  function that holds the NOT_INSTALLED branch. That branch still returns
  before the carve-out check and still fails open.
- **N126** was found in this batch and is remedied above. Team-lead
  confirmed the number.
- **Check-to-run window (N67)**: the launcher is judged at PreToolUse time
  and run afterwards. While the daemon is down every other tool call is
  denied, so only a process that is already running could swap the file in
  between. This is the same boundary class as N71.
- **Exported function**: `_hooks_daemon_stdin_is_recovery_command` is
  exported, but its source variable is not (shellcheck SC2089/SC2090). A
  child shell that has not sourced `init.sh` gets an empty source,
  `python3` exits non-zero, and the call is denied, which fails closed.
  (Round 2 corrects this: D-PATH m3 showed the transport path raises
  NameError and writes no JSON, which does not fail closed. Fixed below.)

## Round 2: the D-RULE and D-PATH findings

Brief: `untracked/scratch/briefs/lifecycle-fix-2.md`. Reviews:
`260926-141113-lifecycle-review-rule-…md` (D-RULE) and
`260926-141211-lifecycle-review-path-…md` (D-PATH). Every finding is fixed
with TDD; the RED evidence is against the round-1 code (`0c6db306d`).

| Finding          | Fix                                                                                                                                                       | RED proof                                                                                                                               |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| F1               | `ensure_daemon` returns at once under a hand-off; `emit_hook_error` shadows every state flag and treats an unnamed event as PreToolUse                    | 14 cases of `TestARelayHandOffReachesOnlyTheCarveOut`; each half, removed in a scratch copy, fails its own cases                        |
| F2 + D-PATH note | Strict std-only `JsonParser`; `is_hand_off_verdict` accepts only a PreToolUse deny with a reason or the context-only answer                               | 20 shapes in `TestTheRelayAcceptsOnlyAVerdictFromTheHandOff`, against a relay built from `0c6db306d`                                    |
| F3 + m2          | `HANDOFF_TIMEOUT_MS` (10 s) with a bounded read, wait and replay; `transport.timeout_seconds` capped at 45 by a validator that says why                   | The never-exiting forwarder test hung past its bound on the old relay; config tests pin the arithmetic, the Rust twin and the validator |
| S1 (N127)        | Compare raw, strip only spaces and tabs, reject anything not printable                                                                                    | 13 control-character cases                                                                                                              |
| `repair`         | Added to `_RECOVERY_SUBCOMMANDS`, same rule                                                                                                               | `TestRepairIsARecoveryCommand`                                                                                                          |
| m1               | The absolute launcher, shell-quoted as `_recovery_command` prints it, is exempt from any `cwd`; every deny (transport, `emit_hook_error`, relay) names it | `TestTheAbsoluteLauncherIsExemptFromAnyDirectory`, `TestTheRelaysOwnDenyNamesTheAbsoluteLauncher`                                       |
| m3               | The source is the exported function `_hooks_daemon_recovery_py` (`printf -v`, no fork); `start_daemon` un-exports it in the launch subshell               | `TestExportedFunctionsCarryTheirOwnRecoverySource`; the daemon-env test fails when the un-export is removed                             |
| S2 (N128)        | `cleanup_pid_file(path, pid)` removes only its own pid; `cmd_stop` removes the socket only on `NOT_LIVE`; `is_daemon_running` re-reads before `rm`        | `TestCmdStopCleansUpOnlyWhatItStillOwns`, `test_paths.py` successor tests, `TestIsDaemonRunningRemovesOnlyItsOwnStalePidFile`           |

### Decisions worth checking

- **F1 has two layers on purpose.** The `ensure_daemon` short-circuit stops
  a start (which could spend the whole hand-off budget) and the CI
  passthrough, which replaces `send_request_stdin` and so never reaches
  `emit_hook_error`. The `emit_hook_error` shadowing covers the source-time
  guards, which fire before `ensure_daemon` and name no event. The relay
  only hands over PreToolUse calls, so an unnamed event under a hand-off is
  that call.
- **F2's accepted shapes** are exactly what `init.sh` writes under a
  hand-off: `emit_error_json`'s deny (with `additionalContext`),
  `emit_hook_error`'s deny, and the carve-out's context-only answer. An
  explicit `allow` is refused: nothing on the hand-off path writes one, and
  it would skip Claude Code's permission prompt.
- **F3's limit** is the 60 s `timeout` the daemon registers for PreToolUse
  in `settings.json` (`hook_registration`, now reading
  `Timeout.REGISTERED_HOOK_TIMEOUT`). Claude Code's own default is 600 s,
  per the vendored `remote-docs/code.claude.com/docs/en/hooks.md`, which
  also confirms that a timed-out PreToolUse command hook lets the call
  continue. `install.py` still writes a literal `60`; it is standalone and
  I did not touch it.
- **m3: function, not exported variable.** Exporting the variable tripped
  shellcheck SC2089/SC2090 in a client-owned asset
  (`test_client_owned_asset_lint.py`), and suppressions are not allowed. A
  function assigning through `printf -v` avoids both that and a fork per
  hook. Exported functions all reach the daemon's environment; this one is
  un-exported for the launch.
- **m1 quoting:** a project path that needs quoting is exempt only in the
  exact `shlex.quote` form the deny prints. Unquoted, bash would split it.
  The relay's `shell_quote` is a twin of `shlex.quote`, and a test compares
  the two outputs for a path with a space.
- **S2 residual:** compare-then-unlink is not atomic; the window is now the
  gap between one read and one unlink, instead of the whole stop sequence.
  POSIX has no unlink-if-content primitive.
- **N68** is unchanged. Under it I cited D-PATH S1 (a moved checkout exits
  127 and the call proceeds) and D-RULE S2 (the fail-open states).

### Hooks-daemon guard defects hit while working (not fixed here)

- `secret_file_guard` denied an `Edit` of `init.sh` whose Python used a
  list comprehension and indexing inside a single-quoted shell string
  (`R-SECRET-SCRIPT-AUTHOR`, "matched `.vault-pass*`"). It also crashed
  with `TooManyToEnumerateError` (`R-SECRET-EVALUATION-ERROR`) on a Bash
  heredoc and a brace group containing globs. I avoided the shapes rather
  than work around the guard. Both look like bracket and brace expansion
  being enumerated over code text; worth an issue.

### Verification (round 2)

- Every test file that references `init.sh` or the relay, plus
  `tests/unit/daemon/test_cli*`, `test_enforcement.py`,
  `tests/daemon/test_paths.py`, `test_transport_config.py` and
  `test_hook_registration.py` (153 files): 2727 passed, 11 skipped, and 3
  setup errors in `test_wrapper_subprocess_env.py`, which refuses to run
  against a daemon older than the working tree. After
  `bin/hooks-daemon restart` (RUNNING; the stop ran the new
  `_release_stopped_daemon_files`) that file passed 4/4.
- `relay/test_relay.py`: 13/13. The relay builds with `-D warnings`.
- `shellcheck -x init.sh`, ruff, black, mypy and pyright: clean on every
  touched file.
