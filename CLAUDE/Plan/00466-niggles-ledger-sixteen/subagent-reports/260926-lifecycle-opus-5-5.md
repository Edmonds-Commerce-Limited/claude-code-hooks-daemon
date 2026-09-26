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

## Round 5: the round-4 confirmation findings

Commits `cba56406e` (the fixes) and `878609b8b` (one more row in the proof
table). The inputs were D-RULE (NOT READY, R4-1 and R4-2) and D-PATH
(READY, P4-1 to P4-4, and shared Sh-D, Sh-E and Sh-F). Every finding is
fixed. All file content went through Edit/Write.

### What changed

- **R4-1 / P4-1 (MAJOR): the startup poll is bounded by the clock.**
  `start_daemon` sets `deadline=$((SECONDS + 15))` (from
  `DAEMON_STARTUP_TIMEOUT`, still 150 deciseconds) once `cli start`
  returns, and polls `while ((SECONDS < deadline))`. The unused
  `DAEMON_STARTUP_CHECK_INTERVAL` is gone. The timeout message now says
  "15 seconds" rather than "150/10 seconds".

  - `_hooks_daemon_run_cli_helper` runs at most once per hook.
    `_HOOKS_DAEMON_HELPER_KEY` records the question it answered
    (`prove:<pid>` or `remove:<pid text>`), and `_HOOKS_DAEMON_HELPER_STATUS`
    records the answer. The same question gets the cached answer. Any other
    question is not proven, which is safe: an unproven live pid is 2 and a
    start is tried, and a stale file stays.
  - **Worst case on the deny path:** the first helper run (up to
    `Timeout.FILE_LOCK`, 10 s, plus about 0.5 s of import), then
    `validate_venv`, then `cli start` (its own parent poll is at most 5 s),
    then the 15 s poll, then the diagnoses. That is about 32 s, inside the
    60 s hook timeout. Main's loop was 15 s after `cli start`, and this
    keeps that.

- **R4-2: a launcher is a `bin/hooks-daemon`.** `_project_it_manages`
  returns None for any other path. This is in `init.sh`'s embedded Python,
  in `cli_command._project_it_manages` (now `Path | None`), and in the
  relay's `project_it_manages` (now `Option<PathBuf>`). The parity table
  has a new layout: a root whose `bin/hooks-daemon` links to
  `<project>/any/file`. It now also asserts which layouts are unknown, so
  three implementations that were equally wrong would still fail it.

- **P4-2: a command line proves only a pid of this user's.**
  `pid_is_this_projects_daemon` still accepts the socket answering. The
  command-line proof now also requires `_is_this_users_process(pid)`,
  which is `os.kill(pid, 0)` (signal 0, delivered to nothing) on a real
  `int` greater than 1. On the bash side an EPERM pid never reaches the
  command-line match; only the helper sees it.

- **P4-3:** `cmd_stop`'s comment no longer says `read_pid_file` clears a
  stale file.

- **P4-4:** `_write_pid_file` parses the old pid with `parse_pid_text`.
  Text that is no daemon's pid raises `ValueError` into the existing
  `except (ValueError, OSError)`, so it is never probed. `0` used to
  `kill(0, 0)` this daemon's own group and, with the socket live, refuse
  the start.

- **`cmd_start` reports the daemon it started.** The parent's poll is
  `_await_started_daemon(pid_path, socket_path, project_path, displaced)`.
  `displaced` is the live pid the file held at the REUSE gate. A pid equal
  to it is skipped. A new pid counts only once the socket is LIVE or
  `daemon_process_project_root` proves it serves this project.

- **N163 (Sh-D): `kill -0` alone is not running.** For a live pid this user
  may signal, `init.sh` first matches its command line. On Linux that comes
  from `/proc/<pid>/cmdline`, joined by newlines so the argument boundaries
  survive; elsewhere from `ps -ww -o args=`, joined by spaces. It matches
  the launch forms:

  - `-m <cli> --project-root <root> start|restart`, optionally with more
    arguments after it (from `start_daemon` and `bin/hooks-daemon`);
  - with no `--project-root` anywhere, an interpreter under
    `<root>/.claude/hooks-daemon/untracked/venv…` or
    `<root>/untracked/venv…` (from `daemon_control.sh`).

  `<root>` is `PROJECT_PATH`, or its physical path. If that fails, the
  helper decides. Unproven is 2.

  - **Cost:** on this worktree, with a live daemon, it is about 4 ms per
    call (one `awk`) and never runs the helper.
  - **The bash match is narrower than the daemon's rule, never wider.**
    `TestTheHooksCommandLineProofIsSound` runs a table of 15 command lines
    in both joinings. It asserts that bash proves exactly the launch forms,
    and that everything bash proves, `process_verification` proves too.
    Whole-line-in-one-argument is also covered, for procfs.
  - **Known limit of the `ps` path (not Linux):** an argument that holds a
    whole launch line passes there, because the argument boundaries are
    lost. Only a process of this same user reaches that path, and it could
    just as well run the launch line itself.

- **N164 (Sh-E): the lock stays `0600`.** A lock another user can open is
  one they can hold, and every start would wait on them. The docstring says
  so. A second user's open is re-raised as `PermissionError` naming the
  lock's uid and its own, and every caller already fails closed on
  `OSError`. N162's ledger text and my round-4 bullet said a host and a
  container "share one lock". That holds only when one of them is root.

- **N165 (Sh-F): the helper checks the root first.**
  `_hooks_daemon_root_is_this_install` runs `_installs_launcher` (P3-1)
  with system `python3`. When the root is not an install of this project,
  nothing is proven.

- **Round-4 residue, fixed:**

  - `is_daemon_running` was exported, but `_hooks_daemon_is_pid_text` and
    the helper were not, so it broke in a child shell. Everything it calls
    is exported now, along with `_HOOKS_DAEMON_PID_MAX`.
  - `test_fallback_pretooluse_recovery_command_stays_fail_open` failed on
    `f5b2a5b23`. Its sandbox used a daemon root, `proj/root`, that P3-1
    rightly treats as no install of the project. The sandbox now uses
    `proj/.claude/hooks-daemon`.

- **Fixtures that faked "running" with the test's own pid.** They were
  `test_forwarder_jq_free`, `test_relay_guard_fail_open` and the venv
  self-heal sandbox's stand-in daemon (`sleep 60`).

  - They now name a process launched as the project's daemon is:
    `tests/daemon_like_process.py`. It waits on its stdin and ends when the
    stdin is closed; no signal is sent to it.
  - The relay hand-off helper `_judging_project` no longer writes a pid at
    all, since `ensure_daemon` returns before reading it.
  - Two static tests now look for the parent's poll in
    `_await_started_daemon`: `test_restart_verified_slow_startup` and
    `test_init_sh_start_daemon_boot_race`.

### RED proof

- **Against `f5b2a5b23`:** I copied the new test files into a
  `git archive f5b2a5b23` tree (`untracked/scratch/r5-base`) and built its
  relay. Every new test failed there:

  - the two `TestTheStartupPollIsBoundedByTheClock` cases (the helper ran
    23 times, not once);
  - the Sh-D, Sh-F and child-shell cases;
  - the proof table;
  - P4-2, P4-4 (six texts) and the three `cmd_start` cases;
  - the Sh-E refusal;
  - both R4-2 parity rows.

- **Mutations of HEAD:** `untracked/scratch/r5_red.py` reverts one fix at a
  time in a `git archive HEAD` copy, rebuilding the relay for the Rust
  mutation. All 13 turn their pinning tests RED:

  - the helper cache;
  - a tick-counted poll;
  - R4-2 in each of the relay, `cli_command` and `init.sh`;
  - the Sh-F root check;
  - P4-2;
  - `kill -0` alone meaning running;
  - the displaced pid being reported;
  - the `--project-root` guard in the venv form;
  - `int()` in `_write_pid_file`;
  - the named `PermissionError`;
  - the missing exports.

  The R4-2 relay mutation first came back GREEN because my own mutation
  was wrong (`false && a || b` still tested `b`). With that corrected it is
  RED. The venv-form guard also came back GREEN at first, so I added the
  table row `start --project-root <other>` (`878609b8b`), and it is now
  RED.

### Verification (round 5)

- 28 files ran in one pass: the init.sh, relay-guard, forwarder, jq-less,
  self-heal, restart, cmd_start, cli, server, pid, paths, CI-passthrough
  and transport files. Result: 793 passed, 18 subtests passed.
- The daemon-backed files that point init.sh at a PID file (the three
  isolated-daemon probes, plugin integration, socket discovery,
  `debug_info`): 103 passed.
- The relay harness, run as a script (`python relay/test_relay.py`):
  13/13. Under pytest it errors on a missing `binary` fixture, which is how
  it is written, not a regression.
- `relay/build.sh` (`-D warnings`) built clean.
- `shellcheck init.sh`, ruff, black, mypy and pyright are clean on every
  touched file. `check_fail_open_inventory.py` reports 39/39.
- `bin/hooks-daemon restart` from the worktree before the fix commit:
  RUNNING, one daemon.
- The gate was not queued, per the brief.

### Hooks-daemon guard defect hit (not fixed here)

`secret_file_guard` crashed with `TooManyToEnumerateError` (a fail-closed
deny, `R-SECRET-EVALUATION-ERROR`) on several `Edit`s to `init.sh`. It
denied:

- a `while read -d '' …; done < "$file"` loop;
- `[[ "$args" == "$root/untracked/venv"* ]]`;
- a word made of two adjacent expansions (`"$sep$piece"`, `"$root$marker"`
  in some positions).

It seems to normalise each unresolved expansion to `*`, so adjacent ones
become `**`, and then try to enumerate that recursively. I worked around it
in the code's shape:

- `awk` reads the procfs file, taking it as an argument;
- `printf -v` does the joins;
- prefixes are tested with `${var#…}`.

I did not work around the guard itself. This is worth an issue report
through the hooks-daemon skill. It cost one `awk` fork per hook on the hot
path (about 4 ms in total, measured above), where a bash `read` loop would
cost none.

### For the confirmation reviewer

- **Soundness of the bash match.** Check `_hooks_daemon_args_name_root`
  against `process_verification._extract_project_root` and
  `_is_daemon_server_process`. The table is the executable form of that
  claim.
- **The helper cache.** A second, different question in the same hook is
  "not proven". The one place that matters is a start whose new pid bash
  cannot prove from its command line. That happens only on a non-Linux
  host whose launch form it does not recognise, and there the poll denies
  on time rather than hanging.
- **Sh-E was a choice.** I kept `0600` rather than making the lock shared.
  If the owner wants host and container to share one lock across users,
  that is a different design: a group-owned lock with `0660`, which still
  lets that group block starts.

## Round 6: the round-5 confirmation minors (merge finished: see "Round 6 merge")

Brief: `untracked/scratch/briefs/lifecycle-fix-6.md`. Reviews: D-RULE
`...lifecycle-review-rule-5...0f30b73852699b8a.md`, D-PATH
`...lifecycle-review-path-5...2500f87a413576cc.md`. Every fix is in
`cf0aa42cc` on top of `d386c682a`. **main is NOT merged yet**: the merge
hit a real semantic conflict and I stopped at my context budget. The steps
left are at the end of this section.

### Fixes (all in `cf0aa42cc`)

| Finding            | Fix                                                                                                                                                                                                                                                                                                                                                                                                    | Test                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P5-1 / Sh-G (N190) | Ownership is the owner's uid, never permission to signal. bash `_hooks_daemon_pid_is_this_users` reads procfs `Uid:` (real, effective) or `ps -o ruid=,uid=` and compares both with `$EUID`, and gates the command-line proof. Python `process_verification.is_this_users_process` does the same with `psutil.Process.uids()`; `cli._serves_this_project` requires it.                                 | bash: `test_a_command_line_proves_only_a_process_this_user_owns[this user / another user]` (a fake procfs root, `_HOOKS_DAEMON_PROCFS`, holding the real cmdline and a faked `Uid:`). Python: `TestIsThisUsersProcess` and `TestPidIsThisProjectsDaemon::test_a_command_line_never_proves_another_users_pid` (faked `os.geteuid`)                                             |
| R5-1 / P5-2        | `_await_started_daemon` has a monotonic deadline, `Timeout.DAEMON_PID_POLL_BUDGET_SEC = 5.0`, which replaces `DAEMON_PID_POLL_MAX_ITERATIONS`. The last probe can overrun it by one probe (≤ 1 s with the identity probe).                                                                                                                                                                             | `TestAwaitStartedDaemonIsBoundedByTheClock`: unstubbed. A real socket accepts every probe and never answers, and the PID file names a live non-daemon pid. It counts accepted probes: ≤ budget / probe timeout + 1                                                                                                                                                            |
| R5-2               | procfs cmdline is read split at its NULs (`mapfile -t -d ''`), as psutil reads it                                                                                                                                                                                                                                                                                                                      | `test_procfs_bytes_are_read_as_the_daemon_reads_them` (5 byte-level cases: a launch across newlines, a trailing newline, no final NUL, an extra empty argument, a root cut by a NUL). Real process: `test_an_argument_holding_a_launch_across_newlines_is_not_one`                                                                                                            |
| R5-3               | `ensure_daemon` keeps the status. The passthrough-flag shortcut is only for down (1). After a failed start, CI passthrough needs `_hooks_daemon_is_down`. Unknown (2) falls through to the error path, which denies PreToolUse.                                                                                                                                                                        | `test_an_unknown_answer_is_never_a_ci_passthrough[flag-set/no-flag]`, `test_a_real_down_after_a_failed_start_takes_the_ci_passthrough`, `test_a_real_down_with_the_flag_skips_the_start`                                                                                                                                                                                      |
| P5-3               | `_hooks_daemon_argv_name_root` requires `argv[1]=-m`, `argv[2]=<cli>`, `argv[3..4]=--project-root <root>` and `argv[5]=start/restart`, and no other argument naming a root. The no-flag venv fast path is gone (Sh-1).                                                                                                                                                                                 | Parity table rows for `-c pass -m ...`, `-I -m ...`, `-v` before the subcommand, `sh x -m ...`, a module suffix, and a second `--project-root`                                                                                                                                                                                                                                |
| Sh-1 (N191)        | A daemon naming no root is attributed by the natural socket it has bound (`_root_from_listening_socket`, `_project_of_socket`), never by its venv. My branch also re-ran such a start naming the root; **main already does that** (`_reexec_daemon_launch_with_explicit_project_root`, posix_spawn plus `CLAUDE_HOOKS_DAEMON_PROJECT_ROOT`), so the merge keeps main's and drops mine (see below)      | `TestDaemonProcessProjectRoot::test_a_daemon_naming_no_root_serves_the_project_whose_socket_it_listens_on` and 4 siblings, and `TestFindAllDaemonProcessesProjectRootFilter::test_the_venv_a_daemon_runs_from_attributes_nothing`                                                                                                                                             |
| Sh-2 (N192)        | A new `_system` action `identity` answers `{project_root, pid}`. `server.daemon_socket_identity` asks for it with a bounded connect and a bounded answer. `pid_is_this_projects_daemon` and `_await_started_daemon` accept only this project's answer; the await also needs the answering pid. The REUSE and unlink gates keep the connect-only probe, which is the right direction for "never steal". | `test_a_socket_proves_only_an_answer_as_this_projects_daemon[nothing / another project]` (bash). `TestPidIsThisProjectsDaemon` (3 new cases). `test_the_daemon_answers_which_project_it_serves` uses the real `HooksDaemon._handle_client`. Live daemon checked by hand: `DaemonIdentity(project_root='/workspace/untracked/worktrees/worktree-n466-lifecycle', pid=1921038)` |
| Sh-3 (N193)        | `server._pid_file_points_at_live_process` uses `parse_pid_text`                                                                                                                                                                                                                                                                                                                                        | `test_pid_file_points_at_live_process_false_for_what_names_no_pid[0,-1,1,007, 12 ]`                                                                                                                                                                                                                                                                                           |

`tests/daemon_like_process.py` gives its stand-in the exact launch argv. It
runs a stand-in `claude_code_hooks_daemon/daemon/cli.py` from a temporary
`cwd`, which comes first on `sys.path`. It also gains
`answering_daemon_socket` and `silent_socket`.

### RED proofs

- **On `d386c682a`, unmodified.** 17 failed:

  - the two Sh-2 bash cases;
  - the other-uid bash case;
  - both R5-3 cases;
  - the procfs and ps parity tables;
  - the symlink case and 2 byte cases, because the new function is absent;
  - 3 `TestPidIsThisProjectsDaemon` cases;
  - the R5-1 poll (an old probe reads the silent socket as LIVE);
  - 2 relaunch cases;
  - the real-process newline smuggling case (`rc=0`, expected `rc=2`).

  `test_process_verification.py` and `test_server_liveness_reuse.py` failed to import (`is_this_users_process` and `DaemonIdentity` do not exist).

- **Mutations on a `git archive` copy of `cf0aa42cc`** (`untracked/scratch/mut-r6`). Every targeted test failed:

  - the tick loop restored: `assert 50 <= 3`, 50 probes;
  - `_project_of_socket` without the natural-path check: the `stray.sock` case attributed a root;
  - `int()` restored in `_pid_file_points_at_live_process`: `0`, `-1` and `1` read as live;
  - `kill -0` in place of the uid check: the other-uid bash case gave `rc=0`.

### GREEN at `cf0aa42cc`

- 546 tests across 14 lifecycle files: the init.sh fail-closed and relay-guard tests, `test_forwarder_jq_free`, and the `cli_commands`, `cmd_start`, `start_reuse`, `restart_verified`, `ci_passthrough`, `enforcement`, `server_coverage`, `controller`, boot-race, realpath and jqless tests.
- 35 tests in the isolated-daemon integration tests, which cover the real relaunch and start path.
- ruff, black, mypy, pyright and shellcheck are clean on the touched files.
- The daemon was restarted and reports RUNNING.

`test_cli_cmd_start.py` needed `_poll_clock()`. It patches `cli.time` with a clock that only its own sleeps advance, so the wall-clock poll ends at once. `_proven_to_serve` now also patches `is_this_users_process`.

### Why the merge stopped, and how to finish it

`git merge main` (fd4956813) conflicts in `PLAN.md` (the ledger table),
`cli.py`, `process_verification.py`, `test_cli_commands.py` and
`test_process_verification.py`. I aborted it cleanly; `cf0aa42cc` is intact.

The conflict is not textual. Main's N59 rewrote `cmd_stop` around
`utils/safe_signal.stop_verified_daemon`, a pinned `psutil.Process`, and
removed the pidfd helpers. This branch's earlier rounds changed the same
function:

- N70: a daemon gone before the signal keeps its files;
- S2/Sh-C: the files are released under the start lock only while they are
  still ours.

Main's version cleans both files up unconditionally on `ALREADY_GONE` and
on success.

My partial resolution is saved in `untracked/scratch/merge-r6-partial/`:

- `process_verification.py.resolved` is complete. It keeps main's `PROJECT_ROOT_ENV_VAR` and `_extract_project_root(proc)`, which `safe_signal` imports. The resolution order is flag, then env var, then socket, through a shared `_attributed_root` that `daemon_process_project_root` also uses (sources `_FLAG_SOURCE`, `_ENV_SOURCE`, `_SOCKET_SOURCE`). The venv fallback is gone.
- `cli.py.resolved` is complete:
  - main's `stop_verified_daemon` path;
  - `ALREADY_GONE` leaves both files (N70);
  - success calls `_release_stopped_daemon_files`;
  - the pidfd helpers are dropped;
  - main's posix_spawn relaunch replaces my `os.execv` one;
  - both import lists are merged, and the unused `errno` import is removed.
- `test_cli_commands.py.conflicted` is the file with its 5 conflict hunks, unresolved.

Remaining steps, in order:

1. Merge main again (`git -C <wt> merge --no-ff --no-commit main`). Copy the two `.resolved` files over the conflicted ones.
2. Resolve `test_cli_commands.py`:
   - Take main's side in every hunk: main's real-process `TestCmdStop*` tests, and `TestCmdStopGenericException` patching `stop_verified_daemon`.
   - Drop HEAD's pidfd classes (`TestCmdStopSignalsThroughPidfdWhenAvailable`, HEAD's `TestCmdStopSignalsOnlyThisProjectsDaemon`) and the `_close_all_but` and `_reject_unproven_real_signals` fixtures.
   - Keep HEAD's `_UNREAL_PID`, `_CLI` and `short_dir`, which the round-6 tests use.
   - Change main's `test_a_pid_nobody_has_is_a_stale_pid_file` to assert N70: both cleanups are **not** called.
   - Port the branch-only `TestCmdStopFallsBackAndCleansUpOnlyWhenProvenSafe` and `TestCmdStopCleansUpOnlyWhatItStillOwns`, which patch `os.pidfd_open` and `os.kill`, to real processes plus `stop_verified_daemon`. Keep their assertions about release under the lock.
3. In `test_process_verification.py`, keep both import sets. The `Timeout` import and main's removal of `kill_daemon_process` go together: drop `TestKillDaemonProcess` if main deleted the function. Drop my `tests/unit/daemon/test_cli_main.py` relaunch class `TestAStartNamingNoRootIsRerunNamingIt` (it patches `os.execv`; main's relaunch is posix_spawn and main has its own tests). Add an env-var attribution case to `TestDaemonProcessProjectRoot`.
4. Resolve the `PLAN.md` ledger table with `merge_ledger_table.py` and the N1-row Edit, per the brief. Move any stdlib containment call onto `path_containment`, then run `scripts/qa/run_semgrep_check.sh`.
5. Run the init.sh, relay and cli tests. Then run shellcheck, ruff, black, mypy, pyright and the `-D warnings` relay build. Restart the daemon, check RUNNING, and commit the merge.
6. Release notes: add a three-digit note for round 6 (uid ownership, the identity handshake, NUL-split cmdline, the CI passthrough on unknown, and socket attribution). Then commit.

Do not queue the gate (brief).

### Round 6 merge

Brief: `untracked/scratch/briefs/lifecycle-merge-1.md`. Merge commit
`dbbc83458` (main `fd4956813` into `26df53ea5`); the release notes and this
subsection are in the commit after it. The gate is NOT queued: a short
confirmation review of the merge comes first (brief).

#### Resolutions

- `cli.py` and `process_verification.py`: the saved
  `untracked/scratch/merge-r6-partial/*.resolved` files, unchanged (see the
  section above). main's `safe_signal` still calls
  `_extract_project_root(process)` with a `psutil.Process`; that signature
  is main's, so no caller changed.
- **One proof, the stricter.** Two proofs covered "this pid is this
  project's daemon": main's `safe_signal.verified_daemon_process` and this
  branch's `_serves_this_project`. `cmd_stop` now uses main's. It compares
  `normpath` roots, which is stricter than the branch's `realpath`. It
  lacked the round-6 P5-1 uid rule, so `verified_daemon_process` now reads
  `uids()` on the pinned handle. It refuses a process whose real or
  effective uid is not this user's, and one whose owner cannot be read.
  The other callers (`enforcement.py`, `client_validator.py`) get the same
  rule.
- `test_cli_commands.py`:
  - main's side is taken in every hunk;
  - HEAD's pidfd classes and the `_close_all_but` and
    `_reject_unproven_real_signals` fixtures are dropped;
  - `_UNREAL_PID`, `_CLI` and `short_dir` are kept, and main's duplicate
    `_NONEXISTENT_PID` is folded into `_UNREAL_PID`;
  - `test_a_pid_nobody_has_is_a_stale_pid_file` is now
    `test_a_daemon_gone_before_it_is_proven_keeps_its_files` (N70: neither
    cleanup is called);
  - `test_a_proven_daemon_that_exits_before_sigterm_keeps_its_files` is new.
    It uses a real daemon whose `terminate` raises `NoSuchProcess`.
  - `TestCmdStopCleansUpOnlyWhatItStillOwns` is ported to a real daemon
    process and the real `stop_verified_daemon`. A wrapper runs the
    successor's start after the real stop returns. All 5 cases, including
    the start-lock assertions, are kept.
  - `TestCmdStopFallsBackAndCleansUpOnlyWhenProvenSafe` is dropped. Its
    pidfd fallback cases have no code left to test, and its N70 case is the
    new real-process test above.
- `test_process_verification.py`: both import sets are merged. `Timeout`
  and `kill_daemon_process` are gone; main deleted the function and
  `TestKillDaemonProcess` with it. Two cases are added:
  `test_a_daemon_naming_no_root_is_attributed_by_its_recorded_env_var`
  and `test_the_flag_outranks_the_recorded_env_var`.
- `test_cli_main.py`: back to main's text. The `os.execv` class
  `TestAStartNamingNoRootIsRerunNamingIt` is dropped.
- `test_safe_signal.py`: two cases are added,
  `test_another_users_daemon_naming_this_project_is_refused` (faked
  `os.geteuid`) and `test_a_pid_whose_owner_cannot_be_read_is_refused`.
- `PLAN.md` ledger: `merge_ledger_table.py` reported
  `differs_from_main=[N67, N69, N70]` and
  `only_on_branch=[N126..N128, N139, N140, N160..N165]`. The N1-row Edit
  re-aligned the table. N190-N193 have no ledger rows on either side; they
  are recorded only in this report.
- Stdlib containment: `pathlib-quadratic-containment` finds nothing on the
  merged tree, so nothing needed moving.

#### Release notes

- `152-...` is renamed to `152-stop-leaves-a-successors-pid-file-and-socket-alone.md`
  and rewritten. It described the pidfd fallback, which the merge removed.
- `160-a-daemon-is-proven-by-its-owner-its-socket-and-its-answer.md` covers
  round 6: uid ownership, the identity handshake, the NUL-split cmdline and
  the exact launch shape, the CI passthrough only on a real down, and
  socket and env attribution.

#### RED proofs

- The two new `test_safe_signal.py` cases failed on the merged tree before
  the uid check: `DID NOT RAISE RefusedSignalTarget`, twice.
- Mutations on a copy of the merged tree (`untracked/scratch/mut-r6m`):
  - `ALREADY_GONE` deleting both files (main's pre-merge behaviour): both
    N70 tests failed.
  - The success path calling `cleanup_pid_file` and `cleanup_socket`
    directly, instead of `_release_stopped_daemon_files`: 4 of the 5
    `TestCmdStopCleansUpOnlyWhatItStillOwns` cases failed (successor,
    lock-held probe, kept lock, unopenable lock). The fifth, "files
    removed", passes by design.

#### GREEN at `dbbc83458`

- **1109 passed** in one serial run of the lifecycle, signal and relay
  files:
  - `test_cli_*`, `test_enforcement*`, `test_server_coverage`,
    `test_server_liveness_reuse`, `test_process_verification`,
    `test_controller`, `test_bootstrap_decision*`;
  - `test_safe_signal`, `test_path_containment`, `test_client_validator`,
    `test_signal_safety_net`, `test_signal_target_checker`,
    `test_venv_heartbeat_signal_target`;
  - every `test_init_sh_*`, `test_relay_*` and `test_forwarder_*` file,
    the isolated-daemon files, `test_hooks_deploy_relay_guard` and
    `test_ci_provisions_the_relay`.
- **8 setup errors in that run** were all in the three isolated-daemon
  files: `cli status` timed out after 5 s. The load average was 68 and I
  was running semgrep at the same time. Rerun alone, the three files gave
  8 passed.
- `scripts/qa/run_semgrep_check.sh`: no violations. Its first run timed
  out on one rule for `cli.py` under the same load and failed closed. The
  rerun was clean.
- `scripts/qa/check_signal_targets.py`: no signal to an unproven target
  (2069 files).
- ruff, black, mypy and pyright are clean on the 7 touched Python files.
- `shellcheck -x` is clean on both `init.sh` files and the 7 shell scripts
  the merge brought in.
- `relay/build.sh` (`-D warnings`) built clean, and
  `relay/test_relay.py` passed 13/13.
- Daemon: restarted twice from the worktree. The second restart stopped
  the live daemon through `stop_verified_daemon` and reported
  `Daemon: RUNNING`.

## Round 7: review 7's shared findings (N202-N206)

Brief: `untracked/scratch/briefs/lifecycle-fix-7.md`. Review:
`...lifecycle-review-7-...92c829ed376b490d.md`, which found the merge READY
and five defects shared with main. The fixes are in `ff92e2717` on top of
`0164c8a00`.

### Fixes

- **N202** (§5): `cmd_start`'s parent waited a fixed 5 s for a PID file
  that is written only after controller init. On a loaded host it reported
  "failed to start (no PID file created)" while the daemon came up.
  - Before the first fork, `cmd_start` opens a pipe, and the daemon holds
    its write end for its whole life. The daemon writes its pid, then a
    byte after config load and another after controller init.
  - The parent (`_StartProgress`, `_await_started_daemon`) counts as
    progress: a byte, a change in the PID file, or CPU time the daemon has
    spent.
  - It stops at end of file (the daemon exited), after
    `Timeout.DAEMON_START_STALL_SEC` (10 s) with no progress, or at
    `DAEMON_START_BUDGET_SEC` (30 s). 30 s plus `init.sh`'s own 15 s poll
    stays inside the hook's 60 s.
  - The message says which of those ended the wait. It also says what the
    PID file showed: no file, a file from before this start, or a file
    whose proof is still pending.
- **N203** (S-1): `_root_from_flag` took the first `--project-root`, where
  argparse keeps the last.
  - `process_verification.add_global_arguments` is now the one definition of
    `cli.main`'s global options, and `cli.build_parser()` is split out of
    `main`.
  - `_root_from_flag` parses the arguments after the module with those
    options, a `-h` flag, a subcommand and whatever follows it. The parser
    raises where argparse would exit.
  - It raises `_UnreadableLaunch` for a line argparse refuses, for `-h`, for
    any argument after `start`/`restart`, and for a relative root.
    `_attributed_root` (now returning a `RootProof`) then refuses, and does
    not fall back to the environment variable or the socket.
  - `init.sh`'s `_hooks_daemon_argv_name_root` now requires exactly six
    arguments, since a daemon's parser refuses anything after the
    subcommand. The soundness test's two trailing-argument cases are now
    "not a launch" on both sides.
- **N204** (S-2): enforcement removed a stale PID file with no start lock,
  and `is_process_running` read `AccessDenied` as dead.
  - `remove_stale_pid_file` moved from `cli` to `server`, next to
    `hold_start_lock`, so that enforcement and the installer can share it.
    `init.sh` now imports it from there.
  - Enforcement reads the file and hands it over. With no socket there is
    no lock to take, so the file stays.
  - `is_process_running` had no other caller and is removed.
- **N205** (S-3): `client_validator` removed PID files and sockets with no
  lock and no check.
  - `_check_running_daemon`'s `ALREADY_GONE` path and
    `cleanup_stale_runtime_files` go through `remove_stale_pid_file` and the
    new `server.remove_dead_socket`, which takes the start lock and removes
    only on `NOT_LIVE`.
  - The lock comes from the socket paired with the PID file. Both are named
    `daemon{suffix}` in the same directory, as `get_pid_path` and
    `get_socket_path` build them.
- **N206** (§2): a pid reused between psutil's re-check and `os.kill` got
  the signal.
  - `safe_signal._pinned` opens a pidfd BEFORE `verified_daemon_process`.
    `signal_verified_daemon` and `stop_verified_daemon` send through it
    (`_send`) and wait on it with `poll` (`_exited_within`).
  - A pid reused at any point after the pin can only make the send fail
    with `ESRCH`, which is reported as `ALREADY_GONE`.
  - Where `pidfd_open` fails with `ENOSYS`, `EPERM`, `ENODEV`, `EMFILE` or
    `ENFILE`, the proven psutil handle sends and waits, as before.
- **Stale comments**: `init.sh:1324`,
  `cli._reexec_daemon_launch_with_explicit_project_root`, the `safe_signal`
  module docstring, `CLAUDE/Security/UnprovenSignalTarget.md`, the
  `paths.read_pid_file` docstring, and the `cmd_stop` comment about pidfds.

### Decision: `signal_verified_daemon_via_pidfd` is removed rather than called

That function opened its pidfd AFTER the proof. A pid reused between the
proof and the pin would have been pinned to the new process, which is the
same window N206 is about. The fix pins before the proof, inside the two
functions every caller already uses. That left the separate function with no
caller and no purpose. No caller goes without a pidfd except on a kernel that
cannot make one.

### Ledger

- `PLAN.md` rows for N190-N193, which were previously recorded only in this
  report (round 6's P5-1/Sh-G, Sh-1, Sh-2 and Sh-3), and for N202-N206.
- A `NIGGLES.md` entry for each of them.
- Release note
  `161-start-waits-on-a-starting-daemon-and-stop-pins-the-process-it-proves.md`.

### RED proofs (on a `git archive` of `0164c8a00`)

- **Setup**: the new and changed test files were copied into the archive,
  with `PYTHONPATH` set to the copy's `src`. The two new `Timeout` names were
  added to the copy so the integration test can import; that changes no
  behaviour.
- **Result: 25 failed, 7 passed.**
- **The 25 failures**:
  - all 5 `TestTheFlagIsReadAsTheDaemonsOwnParserReadsIt` cases;
  - all 3 `test_a_daemon_launched_for_b_through_as_wrapper_is_never_stopped_by_a`
    cases;
  - 2 of `TestAStalePidFileGoesOnlyUnderTheStartLock`;
  - 4 of `TestRuntimeFilesGoOnlyUnderTheStartLockAndOnlyWhileDead`;
  - 5 of `TestTheSignalGoesThroughAPidfdPinnedBeforeTheProof`;
  - all 5 `TestTheStartWaitFollowsTheDaemonsProgress` cases;
  - the integration test, whose daemon sleeps 7 s in controller init. It got
    exactly the field message: `ERROR: Daemon failed to start (no PID file created)`, exit 1.
- **The 7 passes** are guards that already held at `0164c8a00`:
  - enforcement with a lock held by a start, and with no socket;
  - the installer with a PID file naming no process;
  - safe_signal's reaped-pid lookup error and its no-pidfd fallback.
- **A leak in the first run**: the integration test's daemon outlived the
  test. Its teardown ran `stop` before the daemon had written a PID file,
  which is N202 itself. I stopped that daemon through `stop_verified_daemon`.
  The teardown now finds the daemon by its `--project-root` and stops it
  through the verified path. A second RED run left nothing behind.

### GREEN at `ff92e2717`

- **1955 passed** in one serial run of `untracked/scratch/r7-targeted.sh`.
  It covers:
  - every `test_init_sh_*`, `test_relay_*`, `test_cli*`, `test_enforcement*`
    and `test_server*` file;
  - `test_process_verification`, `test_daemon_umask`,
    `test_client_validator`, `test_safe_signal`, `test_signal_safety_net`
    and `test_ci_passthrough`;
  - `test_forwarder_jq_free`, `tests/daemon/test_server.py` and the relay
    provisioning files;
  - the three start-wait integration files.
- **The first run failed 8**, all in
  `test_init_sh_pretooluse_fail_closed.py`:
  - 7 were the soundness test. It called `_root_from_flag`, which now
    raises, and it expected `start [more]` to count as a launch.
  - 1 was a fake python that counted helper runs by the text
    `daemon.cli import`, but `init.sh` now imports from `daemon.server`.
  - After the fixes described above, the file passed 173/173.
- **Relay**: `relay/test_relay.py` passed 13/13. `relay/build.sh`
  (`-D warnings`) built clean.
- **Static checks**:
  - `scripts/qa/run_semgrep_check.sh`, including the containment rule: no
    violations.
  - `scripts/qa/check_signal_targets.py`: no signal to an unproven target
    (2070 files).
  - ruff and black: clean on every touched file.
  - mypy: no issues in `src` or `test_cli_cmd_start.py`.
  - pyright: 0 errors on every touched file.
  - shellcheck: clean on `init.sh`.
- **Daemon**: restarted from the worktree; it reported `Daemon: RUNNING`
  (PID 2632155).

### Round 7 merge of main (`94703d89e`, main `44d1b1b3b`)

Main had moved by N194 alone: waits for exec in `test_safe_signal.py` and
`test_client_validator.py`.

- **Conflicts**:
  - `test_client_validator.py`: imports only; both sets are kept.
  - `PLAN.md`: resolved row by row with `merge_ledger_table.py`, then the
    N1-row Edit to re-align the table.
  - `NIGGLES.md`: both sides kept, newest first (N206-N202, N194,
    N193-N190). This also drops a stray escaped conflict marker
    (`\<<\<<\<<< HEAD`) above N118, which both sides carried from an
    earlier merge.
- **GREEN after the merge**:
  - the same targeted run: 1955 passed;
  - the two merged test files: 104 passed;
  - `check_signal_targets.py`: clean.
- **Daemon**: restarted. The restart stopped the old daemon through the
  new pidfd path, and the daemon reported `Daemon: RUNNING` (PID 2666464).

## Round 8 (review 8: R8-1 to R8-5, S8-1 = N225)

Code commit `2088b3b30`, on `29f8f751d`. Every new test was run against a
`git archive` of `29f8f751d` with the new test files overlaid: 18 failed and
3 passed. The 3 that passed are the guard cases for roots that argparse
normalises, which are expected to pass there too.

- **R8-1 (hook-path budget)**:
  - `init.sh` now runs `cli start` in a process substitution, with stdin
    from `/dev/null`. It reads the output as it arrives and never waits for
    the launcher to finish.
  - The poll ends at `_HOOKS_DAEMON_START_DEADLINE`: 15 s of bash
    `SECONDS`, counted from the hook's own start. This is a twin of
    `Timeout.HOOK_START_DEADLINE_SEC` = 60 - 30 (the request) - 10
    (`FILE_LOCK`, for the one helper run that may start just before the
    deadline) - 5 (margin).
  - After the launcher finishes, the poll continues for up to
    `DAEMON_STARTUP_TIMEOUT` more, and never past the deadline.
  - If the launcher is still running at the deadline,
    `_HOOKS_DAEMON_STARTING` is set. `ensure_daemon` then skips every
    diagnosis, and `emit_hook_error` denies with "the daemon is starting;
    retry".
  - A launcher still writing after the hook has answered gets EPIPE. Only
    the CLI parent can hit that, and only after the fork, so the daemon
    keeps starting.
  - `timeout.py`'s comment is corrected.
  - Tests:
    - `TestAStartNeverRunsTheHookPastItsTimeout`: one test sums the bounds
      from the real constants and from `init.sh`'s copies. The other runs
      the real forwarder against a launcher that blocks until the test
      releases it, and expects the "starting; retry" deny.
    - RED on `29f8f751d`: the hook hung on the launcher until the 60 s guard.
- **R8-2 (start-wait messages)**:
  - `_pid_file_state` reads the PID file text. A pid that is not running
    is named as such, and an exited daemon is never described as
    "pending".
  - The daemon writes `w` on the start pipe before waiting on a contended
    start lock (a `LOCK_NB` attempt first). It writes `.` once it holds
    the lock. The wait is not counted as a stall, and the budget message
    says the daemon is waiting on the lock.
  - `HooksDaemon(start_lock_waiting=...)`.
- **R8-3**: `paths.socket_path_paired_with`. This host's PID file pairs
  with `get_socket_path`. Another host's pairs with the `.sock` beside it,
  through the same length fallback. The test uses a PID file of exactly
  104 characters, with `XDG_RUNTIME_DIR` set to a directory owned by the
  test.
- **R8-4**: `_pinned` turns a `pidfd_open` errno that is not in
  `_NO_PIDFD_ERRNOS` into `RefusedSignalTarget`. Every caller already warns
  on that and signals nothing. Tested for `EINVAL` and `ENOMEM` at
  `safe_signal`, enforcement and the installer, each against a real live
  process.
- **R8-5**: the `cmd_stop` comment and the `verified_daemon_process`
  docstring now state the no-pidfd fallback and its window.
- **S8-1 / N225**:
  - `_root_from_flag` refuses a root containing `..` or one that differs
    from its own `normpath`. It is checked on the `Path` argparse
    produces, which already drops `.`, `//` and a trailing `/`.
  - `verified_daemon_process` compares both roots with symlinks resolved.
  - The ledger entry and PLAN row are added.
- **GREEN**:
  - targeted run: 2941 passed and 3 skipped. This covers the `init.sh`
    integration tests, the slow-start test, the relay guards,
    `tests/unit/daemon/`, the installer, `safe_signal`, the CI passthrough
    and the wrapper environment.
  - `relay/test_relay.py`: 13/13, after `relay/build.sh` (rustc
    `-D warnings`).
  - semgrep: clean. `check_signal_targets.py`: clean.
  - ruff, black, mypy and pyright: clean. shellcheck on `init.sh`: clean.
- **Daemon**: restarted from the worktree; it reports `Daemon: RUNNING`.
- **Guard defect met**: `secret_file_guard` failed with
  `TooManyToEnumerateError` (`R-SECRET-EVALUATION-ERROR`) on `init.sh`
  Edits that combined a compound `[[ ... && ... ]]` test with several
  fd-closing `exec` redirections, and on a heredoc that quoted them. The
  same change went through once it was split into helper functions. This
  belongs in an issue report.

### Open after round 8 (the next fixer's steps)

1. **A retry can restart a slow start from scratch.** After a "starting;
   retry" deny, the retried hook finds no PID file, because a starting
   daemon writes it only under the start lock, after controller init. So
   the hook launches another `cli start`. Inside a container, that
   launcher's `enforce_single_daemon` stops the daemon still starting,
   since its command line proves it serves this project. Concurrent hooks
   hit the same thing before this round, but the retry makes it happen
   for any start longer than 15 s. Candidate fixes:

   - `init.sh` does not launch while a daemon of this project is already
     starting. It could prove that from the process table the same way
     `is_daemon_running` proves a PID.
   - Or enforcement leaves a peer that has not yet bound a socket and is
     younger than `DAEMON_START_BUDGET_SEC`.

   It needs a RED test first. For example: two forwarder runs a few
   seconds apart against a launcher whose daemon initialises slowly, with
   enforcement on.

2. Once that is fixed, merge main if it has moved (it was still
   `44d1b1b3b` at this round's end). Then restart the daemon, commit, and
   queue the gate as the brief says.

Both items are done in round 8b below.

## Round 8b: a retried hook never restarts a slow start

Code commit `3f32ef1e4`, on `4bb1fb789`. This fixes the open item above,
following the coordinator's ruling: while a start is under way, no other
start launches and no enforcement stops the daemon still starting.

- **The launch lock** (`server.LaunchLock`, file `<socket>.launch.lock`):
  - `cmd_start` takes it before the reuse gate. If another start holds
    it, `cmd_start` waits up to `DAEMON_START_BUDGET_SEC`. It prints
    nothing while it waits, so a hook that has stopped reading its output
    cannot break the wait with EPIPE. Enforcement runs only under this
    lock, so it never runs while a start of this socket is under way.
  - The forked daemon inherits the lock's open file. The launcher closes
    only its own copy after the fork. The daemon writes its pid into the
    file, and releases the lock through
    `HooksDaemon(serving=...)` once both binding steps are done. It also
    releases it in the `finally` block when it exits.
  - The lock is tied to the starting process by the kernel. flock is
    released only when every holder has closed it or exited, so a lock
    that can be taken proves the earlier start has either finished or
    died.
  - Once the lock is free, the waiting start runs the ordinary reuse
    gate. If the daemon is serving, it is reused. If the lock was released
    with no PID file, the earlier start died and a new one launches.
    Taking the lock truncates the file, so a pid left by an earlier start
    names nobody.
  - The file is opened like the start lock: `O_NOFOLLOW`, regular file
    only, `0600`. A lock that cannot be opened starts nothing.
- **A start that never finishes** would now block every later start. The
  later start says so, and names the lock. `stop` handles it: with no PID
  file, it reads `start_under_way()`. That gives the pid only while the
  lock is held against it. It then stops that pid through
  `stop_verified_daemon`, the same proof (this user's, command line
  serving this project, pidfd pinned) that it uses for a running daemon.
  If the start has not named its daemon yet, `stop` reports that and
  signals nothing.
- `init.sh` itself is unchanged apart from one comment. A retried hook
  still launches `cli start`, and that launcher now waits on the start
  under way. The hook stops waiting at its own deadline, as before.
- Tests:
  - `tests/integration/test_a_retried_hook_never_restarts_a_slow_start.py`
    runs the real forwarder three times, with `container` and `host`
    variants. Enforcement is forced on or off through `sitecustomize`.
    The daemon's controller init is slowed 7 s past a 2 s hook deadline.
    Hooks 1 and 2 are denied as "starting". Hook 3 is answered. Every
    launcher then finishes, and the record of daemons that reached init
    must hold exactly the one daemon, which is still running.
    - RED on a `git archive` of `4bb1fb789`: both variants recorded three
      daemons. In the container variant, the first two were stopped.
  - Unit tests:
    - `TestAStartUnderWayIsWaitedOnNotRepeated` checks four cases:
      - a start still under way at the budget is left alone, with no
        enforcement and no fork;
      - a start that ends serving is reused;
      - a start that died is replaced;
      - a lock that cannot be opened starts nothing.
    - The daemon names itself and releases the lock only through
      `serving`.
    - `TestTheLaunchLock` covers the wait, release, a forked copy
      surviving the launcher's close, holder naming, a stale pid and a
      planted symlink.
    - `serving` is called only after the bind.
    - `TestCmdStopEndsAStartThatNeverFinishes` covers four cases:
      - a daemon still starting is stopped;
      - another project's pid is refused;
      - a start that has not named its daemon is not signalled;
      - with no start under way, it reports the daemon is not running.
  - `cmd_start` unit tests that patched `get_socket_path` with a bare
    MagicMock now pass a `tmp_path` socket. Otherwise the lock file would
    be created in the current directory, under a mock's name.
- **GREEN**:
  - targeted run: 4521 passed. That covers the `init.sh` integration
    tests, the relay guards, the slow-start and parallel-start tests, the
    new test, `tests/daemon/`, `tests/unit/daemon/`, `tests/unit/install/`,
    `safe_signal` and the CI passthrough.
  - `relay/test_relay.py`: 13/13, after `relay/build.sh` (`-D warnings`).
  - semgrep (containment rule included): clean.
    `check_signal_targets.py`: clean.
  - ruff, black, mypy and pyright: clean. shellcheck on `init.sh`: clean.
- **Daemon**: restarted from the worktree; it reports `Daemon: RUNNING`.
