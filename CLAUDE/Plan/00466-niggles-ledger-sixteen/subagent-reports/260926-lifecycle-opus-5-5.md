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

## Round 3: the round-2 re-review minors

Brief: `untracked/scratch/briefs/lifecycle-fix-3.md`. Reviews: D-PATH
`260926-150213-lifecycle-review-path-2-…md` and D-RULE
`260926-150518-lifecycle-review-rule-2-…md`, both READY. Code commit
`bdd523501`. Every finding is fixed with TDD. The RED evidence comes from a
`git archive` of `1879f881a` with only the new tests laid over it, and a relay
built from that tree: 28 targeted tests fail there and pass here.

| Finding       | Fix                                                                                                                                                                                                                                                                                                           | RED proof (on `1879f881a`)                                                                                                                                                                                                                                         |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| m-A           | The carve-out exempts a spelling only when the file it runs resolves to `<HOOKS_DAEMON_ROOT_DIR>/bin/hooks-daemon`. `_recovery_command`, the relay's `RECOVERY_LAUNCHERS` and the daemon's own transport deny use `cli.py`'s order, clone first. With no launcher, the deny names where the install's belongs | `TestOnlyThisInstallsLauncherIsExempt`: an unrelated root script is denied (relative, absolute and on a hand-off), and never named. Relay: `test_with_both_launchers_it_names_the_clones_first`. Server: `TestTheTransportDenyNamesThisInstallsLauncher` (2 cases) |
| m-B           | `_release_stopped_daemon_files` runs under `server.hold_start_lock` (the flock a start holds across probe, PID write, unlink and bind). If the lock is still held after `Timeout.FILE_LOCK`, it leaves both files                                                                                             | `test_the_probe_and_both_removals_hold_the_start_lock` (each call records whether the lock is held); `test_a_start_that_keeps_the_lock_keeps_both_files`                                                                                                           |
| Shared (N139) | `is_daemon_running` counts only ESRCH ("No such process" in the C locale) as dead. EPERM, or any other failure on a numeric pid, returns 0 and keeps the file. A non-numeric file is still stale                                                                                                              | `test_a_pid_it_may_not_signal_is_alive_and_keeps_its_file` (the builtin is shadowed with its real EPERM text, since root may signal anything)                                                                                                                      |
| R2-1          | If `python3` cannot name the recovery command, `emit_hook_error` switches to a fixed message that says no command is exempt. The jq-less encoder and the transport fall back to `_hooks_daemon_static_deny` (exported)                                                                                        | `TestADenyNeedsNoPython3`: PATH without `python3`, with and without `jq`, for the daemon-down deny and for the transport                                                                                                                                           |
| Cap           | Over the cap, the value is clamped to 45 with one WARNING that names the key, the value, the cap, the reason and the fix. The UNRELEASED manifest has a `changed` entry with the new `maximum: 45` field, which `check-config-migrations` reports only for a number above it                                  | `test_a_timeout_over_the_cap_takes_the_cap_and_warns_why`, `test_a_whole_config_over_the_cap_still_loads`, and `test_relay_timeout_cap_migration_advisory.py` (real manifest tree, `maximum` pinned to `Timeout.RELAY_TIMEOUT_CAP`)                                |
| Shared (N140) | Reading stdin, parsing it and encoding the envelope all happen inside the handler. For PreToolUse, `invalid_hook_input` is a deny: "Hook input could not be parsed, so no guard judged this call"                                                                                                             | `TestInputThatCannotBeParsedIsDenied`: 1000-deep input, every depth from 980 to 1000 (993 parsed, then crashed in `json.dumps` with no answer), non-JSON, non-UTF-8, and a hand-off. Relay: `test_input_nested_too_deeply_to_parse_is_denied`                      |

N139 and N140 are logged and marked ✅ in `NIGGLES.md` and `PLAN.md`. N128's
entry records m-B. The release notes are 152 (m-B) and 153 (m-A and the
cap), plus new notes 154 (N139) and 155 (N140 and R2-1).

### Decision for the coordinator: clamp, do not refuse

An over-cap `daemon.transport.timeout_seconds` now **starts the daemon with
45 and a loud warning**. It is not refused. My reasoning:

- Refusing fails closed and cannot be escaped from inside the session. The
  daemon does not start, so every PreToolUse call is denied, including the
  `Edit` that would fix the config. `restart` and `repair` re-read the same
  config and refuse again. Only a human can clear it. The value in question
  was accepted by main.
- Clamping keeps the invariant the cap exists for. The effective relay wait
  is 45, so wait plus hand-off plus margin still ends before the 60 s hook
  timeout. The forwarder generator bakes `--timeout-ms` from the validated
  model, so the relay gets 45 too. The one thing lost is that the config file
  no longer states the effective value, which is why the warning exists.
- It is reported before it bites. The upgrade advisory names the key, the
  value and 45. The daemon log warns at every load with the key, the cap, the
  reason and the fix. `HANDLER_REFERENCE.md` and note 153 say so.
- The coordinator accepted the clamp and asked for it at SessionStart too;
  see "Round 3 follow-up" below.

### Other choices worth checking

- **"This install" is `HOOKS_DAEMON_ROOT_DIR`.** `init.sh` resolves it from
  `.claude/hooks-daemon.env` or the `.claude/hooks-daemon` default, and
  exports it. The carve-out takes it as a new argument. A relative spelling
  is now exempt from any `cwd` where it resolves to that launcher, for
  example `bin/hooks-daemon` from inside the clone. It still runs the right
  file. The accepted absolute spellings are the two project-rooted ones plus
  `<daemon root>/bin/hooks-daemon`. **Corrected in round 4:** this report
  said "a custom root outside the project is recoverable too". That is
  wrong. The launcher manages the project it derives from its own location
  (`bin/hooks-daemon`), so a root outside the project either restarts some
  other project's daemon or exits 5 ("cannot anchor"). Such a root is now
  treated as unknown and nothing is exempt (P3-1, below). The relay cannot
  read the env file (no config, by design), so it names the first existing
  file in `cli.py`'s order. That is the clone's launcher whenever the clone
  has one. Round 4 replaced this with the shared rule (P3-2).
- **The test fixtures changed shape.** `_make_project` now models a client:
  the launcher lives in the clone, and the root `bin/hooks-daemon` is a link
  to it. `_make_self_install` models this repository. The `test_ci_passthrough`
  and `test_emit_hook_error_jqless` fixtures had a root launcher unrelated to
  their install, which is exactly m-A, so they now link to the install's
  launcher. The three round-2 naming tests expect the clone's launcher first.
- **The daemon's own deny had the same m-A class.**
  `_TRANSPORT_FAIL_CLOSED_REASON` ended with a relative
  `bin/hooks-daemon restart`, which in a client project runs nothing, or runs
  the project's own script. It now ends with `daemon_cli_command("restart")`.
  Not fixed, same class but outside the deny path:
  `cmd_check_source_fresh` prints `Start it with: bin/hooks-daemon restart`,
  and `source_fingerprint._RESTART_ADVICE` says the same. Both are
  daemon-repo developer tooling, where that spelling is right.
- **The EPERM test shadows `kill`.** Root may signal any process, so a real
  EPERM would need a privilege drop. The rules forbid that kind of
  root-conditioned branching. The shadow emits
  `bash: kill: (<pid>) - <os.strerror(EPERM)>`, the builtin's own format.
  The round-2 successor test's shadow now emits the ESRCH text. It really
  was probing a dead pid.
- **`hold_start_lock` polls** with `LOCK_NB` every 50 ms until
  `Timeout.FILE_LOCK`, rather than blocking. A start that wedges while
  holding the lock cannot hang `stop`. Two pidfd tests patched `os.close`
  globally, which would have leaked the real lock fd. They now close every
  descriptor except the fake pidfd, and count that one.

### Verification (round 3)

- The targeted files: `test_init_sh_pretooluse_fail_closed.py`,
  `test_relay_guard_fail_open.py`, `test_cli_commands.py`,
  `test_event_socket_fail_closed_pretooluse.py`, `test_transport_config.py`,
  all of `tests/unit/install/`, `test_ci_passthrough.py`,
  `test_emit_hook_error_jqless.py`, `test_server_liveness_reuse.py`,
  `test_cli_check_config_migrations.py` and
  `test_fail_open_inventory_checker.py`. Result: 1766 passed. Also every
  other `init.sh` integration file, `tests/unit/config` and `tests/config`:
  green.
- `check_fail_open_inventory.py`: 39 scanned, 39 rows. No new boundary.
- `relay/build.sh` (`-D warnings`) built clean; `relay/test_relay.py` 13/13.
- `shellcheck init.sh`, ruff, black, mypy and pyright: clean on every
  touched file.
- `bin/hooks-daemon restart` from the worktree: RUNNING, 31/31 per-event
  listeners.
- Gate not queued, per the brief.

### Round 3 follow-up: the clamp at SessionStart

Coordinator ruling: keep the clamp, and show it at session start as well as
in the log. No new handler was added. The existing config-problem advisory is
`project_handler_load_checker`: it already names project handlers that failed
to load and built-in handlers running on their defaults (N19,
`_option_failures`). The clamp reaches it by the same injection idiom.

- `TransportConfig` clamps in a `model_validator(mode="after")` and keeps
  the configured value in a private attribute. `timeout_problem` is the one
  text, used by both the log warning and the advisory.
  `DaemonConfig.config_problems` collects such problems, currently only this
  one.
- `_build_initialised_controller` passes `config_problems` to
  `DaemonController.initialise`. That logs them, reports them in `health` as
  `config_problems` (not a degraded reason, since every guard is on), and
  hands them to `register_all`. `register_all` injects them into any handler
  that declares `_config_problems`.
- The checker matches on them and adds a `⚠️ CONFIG VALUE NOT IN FORCE`
  block. The block lists each problem with its fix, then gives the restart
  and `health` commands. `verify_still_needed` is unchanged, so the tier
  stays ACTION_SUGGESTED rather than ACTION_REQUIRED. `get_claude_md` covers
  the new alert.

RED (8 tests, run before the implementation, all failing):

- `test_transport_config.py`: the clamp is kept as a problem; none within the
  cap.
- `test_cli_config_fingerprint_wiring.py`: the builder passes
  `config_problems`.
- `TestConfigProblemsReachSessionStart` in `test_controller.py`: a real
  `initialise` → the SessionStart checker names it; `health` names it and
  stays healthy; silent with none.
- `TestConfigProblems` in `test_project_handler_load_checker.py`.

All now pass. The wider unit suites (`tests/unit/config`, `tests/unit/daemon`,
`tests/unit/handlers/session_start`, `tests/unit/install`, `tests/config`,
`tests/daemon`) show 5304 passed. The integration tests that reference the
checker also pass. ruff, black, mypy and pyright are clean. The daemon
restarted RUNNING. `HANDLER_REFERENCE.md` and release note 153 now say it is
reported at session start and in `health`.

## Round 4: the final re-review minors

Commits `736f4c5a5` (the fixes) and `c325911ae` (the Python half of Sh-A).
Both round-3 re-reviews were READY; every minor below is fixed.

### What changed

- **N139-A / P3-3: EPERM is unknown, not running.** `is_daemon_running` now
  returns 0 (running), 1 (not running) or 2 (unknown). EPERM, or any other
  failure that is not ESRCH, is running only if liveness proves it:
  `cli.pid_is_this_projects_daemon` returns true when the socket answers
  (`_socket_liveness_sync` is LIVE) or `daemon_process_project_root(pid)`
  equals this project. Bash runs it in the daemon's venv through a new helper,
  `_hooks_daemon_run_cli_helper`. With no venv it cannot prove anything, so
  the answer is 2. Every caller tests the status with `if`, so 2 never skips
  a start. `cli start`'s REUSE gate then decides. With the socket dead, it
  forks, and `_write_pid_file` overwrites the PID file (its `os.kill(old, 0)`
  PermissionError is already caught). The file of a live pid is never
  deleted. That includes `read_pid_file(verify_daemon=True)`, which used to
  remove the file of a live non-daemon.

- **P3-1: "this install" is anchored to what the launcher manages.**
  `_installs_launcher(project, root)` resolves `<root>/bin/hooks-daemon` and
  applies the launcher's own anchoring rule from `bin/hooks-daemon:279-284`:
  the parent of `bin/` is the daemon dir, and `<p>/.claude/hooks-daemon`
  anchors to `<p>`. It then requires the result to equal the resolved
  `PROJECT_PATH`. If they disagree, or either path is relative, the install
  is unknown. Nothing is exempt, including this project's own launchers, and
  every deny ends with `_recovery_advice`'s text instead. That text says
  `HOOKS_DAEMON_ROOT_DIR (<value>)` is not an install of this project, may be
  inherited or set in `.claude/hooks-daemon.env`, and gives the `!` command
  a human can run. The round-3 "custom root is recoverable" sentence above is
  corrected in place.

- **P3-2: one resolution rule, three implementations, one test table.** The
  rule is `_resolve` (realpath of the longest existing prefix, with the rest
  appended), `_project_it_manages` and `_installs_launcher`. The launcher
  named is the first of `<p>/.claude/hooks-daemon/bin/hooks-daemon`,
  `<p>/bin/hooks-daemon` and `<root>/bin/hooks-daemon` that runs it, or
  `<root>/bin/hooks-daemon` if none does, shell-quoted. It lives in:

  - `init.sh`'s embedded source;
  - `cli_command.install_recovery_command` / `recovery_command`, which the
    daemon's transport deny now uses in place of `daemon_cli_command`
    (that one was never quoted);
  - `hooks_relay.rs` (`resolve`, `project_it_manages`, `installs_launcher`,
    `restart_command`).

  The relay learns the daemon root from `HOOKS_DAEMON_RELAY_DAEMON_ROOT`,
  which the generated guard sets on its `exec` line. It is the untracked
  dir's parent in both install modes. It is an environment variable rather
  than a flag because an older relay binary rejects an unknown flag with a
  usage error, which would leave the hook without JSON. The relay strips it
  from both children. Without it (an older forwarder), the relay uses
  init.sh's default, `<p>/.claude/hooks-daemon`. The 27 tracked forwarders
  are regenerated for the root they record.
  `test_init_sh_the_relay_and_the_daemon_name_one_launcher` runs six layouts,
  each with and without a space in the path, through all three
  implementations and asserts they agree. That test is the detector the
  review proposed. The six layouts are: client; client plus its own root
  tool; client with no clone launcher plus its own tool; self-install with a
  linked clone; self-install with a real clone file; another project's root.

- **Sh-A (N160): stale removal is under the start lock.** Bash no longer
  runs `rm`. It calls `cli.remove_stale_pid_file(pid_path, socket, seen)`,
  which holds `hold_start_lock`. It removes the file only while the file
  still holds exactly the text bash read, and that text names no live pid. A
  held lock (`StartLockTimeout`) leaves the file, and so does a lock that
  cannot be opened or a missing venv. That is harmless: a stale file never
  counts as running, and a starting daemon overwrites it. Fixing this turned
  up the same unlocked compare-then-remove in Python's `read_pid_file` for a
  dead pid. That is removed too (`c325911ae`), so only lock holders remove a
  PID file.

- **Sh-B / S-R3-1 (N161): corrupt PID files.** `paths.parse_pid_text` and
  init.sh's `_hooks_daemon_is_pid_text` share one definition:
  `[1-9][0-9]{0,6}`, in the range 2 to `PID_MAX_LIMIT` (4194304, Linux's
  kernel ceiling), optionally followed by newlines. A test pins the two
  constants equal. `0`, negatives, `1`, `007`, `+12`, `1_2`, text, empty and
  undecodable files are corrupt. They never count as running, and
  `is_daemon_running` removes them under the lock.

- **Sh-C (N162): the start lock.** `_open_start_lock` uses
  `O_NOFOLLOW | O_CLOEXEC` and then `fstat`-checks for a regular file, so a
  FIFO or device is refused with `EINVAL`. There is no ownership check. A
  host and a container sharing the untracked dir run as different uids and
  share this one lock, and the lock is only ever flocked, never written or
  truncated, so an owner check would break a supported layout for no gain.
  `_release_stopped_daemon_files` now catches `OSError` and fails closed: it
  leaves both files and prints a warning, and `cmd_stop` still returns 0,
  because the daemon did stop.

- **D-PATH note 1: an over-cap forwarder timeout.** Upgrade already
  redeploys forwarders: `upgrade_version.sh:944` calls `deploy_all_hooks`
  with the venv python, which runs `regenerate_forwarders_for_transport`
  with the clamped config. The relay now also clamps `--timeout-ms` to
  `TIMEOUT_CAP_MS` (45 000) at start, with a stderr line. A test pins it to
  `Timeout.RELAY_TIMEOUT_CAP`. This covers a forwarder that was never
  redeployed.

- **D-PATH note 2: one document.** `send_request_stdin` captures python3's
  stdout, with its exit status appended after a final `x`, so trailing
  newlines survive. On a PreToolUse failure it prints only the static deny.
  Otherwise it prints the captured bytes exactly.

### RED proof

`untracked/scratch/r4_red.py` works on a `git archive HEAD` copy with the
change applied. It reverts one fix at a time, rebuilds the relay where
needed, and runs the pinning tests. The GREEN baseline is 383 passed. Every
one of these 11 mutations turned its tests RED:

01. EPERM returns 0 → `TestIsDaemonRunningRemovesOnlyItsOwnStalePidFile`.
02. The manages-the-project check is dropped →
    `TestADaemonRootOfAnotherProjectIsUnknown`.
03. `rm -f` runs before the locked removal →
    `test_a_stale_pid_file_is_removed_only_through_the_start_lock`.
04. `^[0-9]+$` is used for a pid → the corrupt-file cases.
05. `int()` is used in `read_pid_file` → `test_paths` (5 failures).
06. `read_pid_file` removes the file unlocked again →
    `test_read_pid_file_returns_none_for_dead_process_and_leaves_the_file`.
07. `O_NOFOLLOW` is dropped → `test_cli_commands`.
08. `except OSError` becomes `except StartLockTimeout` → `test_cli_commands`.
09. python3's output is streamed with the deny appended →
    `TestAPython3ThatFailsAfterAnsweringGivesOneAnswer`.
10. The relay names the first launcher file → the parity table.
11. The relay's clamp is disabled →
    `test_an_over_cap_timeout_from_an_old_forwarder_is_clamped`.

### Verification (round 4)

- init.sh, relay, stop, pid, forwarder and enforcement test files (every
  `test_*` named for them, plus `test_paths`, `test_cli_commands`,
  `test_cli_command`, `test_event_socket_fail_closed_pretooluse`,
  `test_dogfooding_hook_scripts` and `test_transport_config`): 1701 passed,
  5 skipped.
- After `c325911ae`, every file that mentions PID files or the start lock
  (the `read_pid_file` / `hold_start_lock` / `pid_file` / `PID_PATH` set):
  1696 passed, 11 skipped. The skips are relay-binary and environment skips
  that were there before.
- `relay/build.sh` (`-D warnings`) built clean. `relay/test_relay.py`:
  13/13.
- `shellcheck init.sh` is clean; I also quoted `return "$_rv"`, which it now
  flags. ruff, black, mypy and pyright are clean on every touched file.
- `check_fail_open_inventory.py`: 39 scanned, 39 rows. The new code adds no
  `2>/dev/null`.
- `bin/hooks-daemon restart` from the worktree: RUNNING, before each commit.
- Gate not queued, per the brief.

### For the confirmation reviewer

- **Cost.** The EPERM and stale paths now start the venv interpreter to
  import `daemon.cli`. Only those rare paths do: a live pid the hook may
  signal, and a missing file, never reach it. A removed stale file is gone
  on the next call.
- **A test file written through Bash.** I appended
  `TestInstallRecoveryCommand` to `tests/unit/utils/test_cli_command.py`
  with a heredoc rather than `Edit`, against this project's rule. The
  content passed ruff, black, mypy and pyright, but it skipped the
  Write/Edit content guards. Every other change used Edit/Write.
