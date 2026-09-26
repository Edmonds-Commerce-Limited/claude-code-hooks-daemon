# N24/N40 fixer, round 3: review 2 closure

**Plan**: 00466
**Branch**: `worktree-n466-n24`. This round's work is `642a84190..HEAD`.
**Agent**: Opus 5.5 (continuation fixer)

No full gate was run: fixers do not queue one. Every change was checked with targeted tests, ruff, black, mypy and pyright on the touched files, plus `check_magic_values.py` and `check_fail_open_inventory.py`. The daemon was restarted, and reported RUNNING, before every commit that touched `src/`. Every RED proof below came from mutating a `git archive` scratch copy under `untracked/scratch/n24-red*`.

## Review 2 findings, one line each

- **MA1** (gate red): done in earlier rounds (`73233574b`). Not re-run here, because the gate is the reviewer's step.
- **MA2** (quadratic regexes, GIL sweep, SIGKILL): the regex and escalation work is in `10fce785e`. This round, `dccf63d0f` scopes the SIGKILL, and `12df23f75` turns the sweep into a growth ratio (brief item 3, below).
- **MA3** (relay and per-event socket fail open): done in `a9e8c3716`.
- **MA4** (merge main): done in `8d8af2138`. `7364307a0` renames the stale invariant pair to `_SegmentTracker._resolve`.
- **MA5** (release notes): done in `7dd274c9f`.
  - Note 41 now describes mA4.
  - New note 44 covers self-restart, `stop` SIGKILL and its project scoping, and the new `health` degraded reasons.
- **mA1** (broken pipe fails open): done in `1fdcd5019`.
- **mA2** (`BaseException` kills the daemon): the handler-loop half is in `642a84190`.
  - `7364307a0` adds the `commit_side_effects` catch, which still took only `Exception`. RED: `SystemExit`/`KeyboardInterrupt` escaped `chain.execute()`.
- **mA3** (a saturated dispatcher blocks Stop): `90ff90dfc`.
  - `StragglerHealth.at_capacity` is new, and `health` carries it. The watchdog restarts at the cap at once (within one 10 s check) instead of waiting 120 s for the oldest straggler's age. `straggler_restart_after_seconds: null` still disables self-restart.
  - RED: `at_capacity` did not exist, and the watchdog did not restart on it.
- **mA4** (the validator checks a constant; a rejection turns guards off): `90ff90dfc`.
  - The deadline is checked against `TransportConfig.client_budget_seconds`: the python rung's 30 s, or `transport.timeout_seconds` when the relay or nc rung is enabled and shorter.
  - A shortfall is **reported, not raised**. It is logged, and `health` turns `degraded` with the `chain_deadline` reason and the problem text. `status`/`check` print it.
  - Reason for not raising: a rejected value stops the daemon starting, which leaves every guard off, and the client now fails closed on its own timeout for PreToolUse anyway. Raising would also have made any install with a relay timeout under 25 s fail to start after upgrade.
  - The review's "degraded mode ALLOWs" run came from the probe starting without `--project-root`. The CLI walked up past the invalid nested config into an enclosing project (P2). With `--project-root`, which is how `init.sh` and `bin/hooks-daemon` start the daemon, `start` exits 1 and names the deadline error. I reproduced both.
  - Also fixed: `status`/`check` printed "invalid configuration disabled enforcement" for ANY degraded status, stragglers included. The block now keys on the `config` reason.
- **mA5** (straggler commit ignores cancellation): done in `642a84190`. `b1c987623` makes its test deterministic: it waits for the straggler to leave the dispatcher instead of sleeping 50 ms and hoping.
- **Nit 1** (the drain has no time limit): `40d984811`.
  - `_OVERSIZED_REQUEST_DRAIN_TOTAL_SECONDS` is 2 s, and each read waits at most what is left of it.
  - RED by a deterministic read count on a fake clock: 16,384 reads without the limit, 5 with it.
- **Nit 2** (loosened assertions): `b1c987623`.
  - The reasons are now exact: the dispatch-timeout prefix, the saturation string, and for oversize, the measured size and the limit.
- **Nit 3** (a project handler that raises at import vanishes while the daemon says healthy): `7651d16a5`.
  - `health` gains the `project_handlers` degraded reason and `project_handler_load_failures` (file, event directory, reason).
  - RED: `health` said "healthy".
- **Nit 4** (a 90 KB Write path is slow): `12df23f75`. The whole chain went from 8.3 s CPU to 1.2 s.
  - `tdd_enforcement` built the mirrored path one `Path / segment` at a time, which is quadratic in depth. RED 36x/44x growth; it is one `joinpath` now.
  - The rest was `os.path.realpath`'s lstat per component, repeated by several guards, and per pattern by `secret_file_guard`. New `utils/realpath.py` returns exactly what `os.path.realpath` returns: exhaustively compared over every 4-component sequence of existing, missing, symlinked, dangling, looping, `..` and `.` parts. It binary-searches for the longest lstat-able prefix, and falls back to `os.path.realpath` for a `..` in the missing tail or a symlink loop. It is used by `secret_file_matching`, `workspace._resolve_or_self`, `worktree_paths`, `project_containment`, `docs_qa_edit` and `sensitive_content`.
- **P1** (a per-event socket path over the AF_UNIX limit is skipped silently): `82caf18c2`, added after the coordinator took P1 into scope. Every skip is recorded with its reason: path length, a failed bind, a failed chmod, or a symlinked events dir. `health` goes degraded with an `event_sockets` reason and lists `event_socket_skips`, and `status` and `check` name each event. No second fallback directory: the events dir already falls back to a short one when the natural path overflows. RED: 4 tests failed before the fix.
  - The same RED run found a stale test. It sent malformed JSON to the PreToolUse socket and expected `{}`, but that socket has denied since MA3. It now uses `post-tool-use`; the PreToolUse deny is pinned in `test_event_socket_fail_closed_pretooluse.py`.
- **P2, nested layout** (cwd walk-up adopts an enclosing project's config): `c86f4d7ad`. A directory whose `.claude/` holds `hooks-daemon.yaml` is now the project root whether or not that config loads. A broken config there exits 1 with its own error. `load_transport_config` reads only the project root's config, no longer `ConfigLoader.find_config`'s upward search. RED: 2 of 3 new `TestGetProjectPath` tests failed, and 1 transport test failed.
- **P2, degraded mode ALLOWs `curl | bash` and skips project SAFETY handlers**: not fixed on this branch. Plan 00421's branch `worktree-d-00421` (review-2 round) already fixes it, and the coordinator has been told. Its `daemon/degraded_mode.py` runs every SAFETY or BLOCKING built-in and project handler at defaults, widened by the last-known-good snapshot and HEAD's config. A `FailClosedGuard` stands in for a guard it cannot build. It has RED-tested cases such as `test_degraded_mode_still_blocks_curl_pipe_shell`. **N43 has the same root cause** (a degraded daemon resolves nothing through its config), and that branch's `use_degraded_word_lists` fixes it. A second mechanism here would duplicate that one and conflict with it in `controller.py`.
- **`CLAUDE_HOOKS_SOCKET_TIMEOUT` below the deadline**: `e6a80b0c5`. The deny stays. Its reason, context and stderr line name the variable and its value, and say it is shorter than the daemon's chain deadline. `init.sh` carries a pinned copy of `Timeout.CHAIN_DEADLINE_DEFAULT`, held equal by a test, so the comparison uses the default: the client cannot see a project that configures a different deadline. RED: 2 tests failed before the fix.

## Brief items

- **SIGKILL scoping**: `dccf63d0f`.
  - `read_pid_file(verify_daemon=True)` proved only "some daemon server". The new `daemon_process_project_root(pid)` returns the realpath'd root from the process's own `--project-root` (or its venv path). It refuses a non-`int` pid (MagicMock, bool), pid \<= 1, and this process.
  - `cmd_stop` now handles three cases:
    - Root unprovable: it signals nothing and exits 1.
    - Root is another project's: it treats the PID file as stale and signals nothing.
    - Otherwise: it re-takes the proof immediately before SIGKILL.
  - RED by mutating out each guard. A real `bin/hooks-daemon restart` still works.
- **Item 1**: covered by mA3 and mA4 above.
  - **Composition with N53**: N53's shape (`EventIDMeta.chain_deadline_seconds`, `CHAIN_DEADLINE_WORKTREE` = 330) is not on this branch. At merge, N53's per-event check (each event's deadline against its own socket timeout) belongs inside `DaemonConfig.chain_deadline_problems`, using `TransportConfig.client_budget_seconds` as the fallback budget for an event that declares none. It then reports through the same `chain_deadline` health reason. Its `ValueError` must become a reported problem, for the mA4 reason above.
  - N53's `restart_eligible_oldest_age_seconds` and this round's `at_capacity` both touch `StragglerHealth` and the watchdog. The merge needs both, so a worktree straggler at the cap still counts toward `at_capacity` (the cap refuses everything regardless).
- **Item 2**: all four nits done (above).
- **Item 3** (GIL sweep as a ratio): `12df23f75`.
  - `tests/scaling.py` compares thread CPU time at N and 8N. The threshold is 24 (linear gives about 8, quadratic about 64). The denominator is floored by one Python-level pass over the large input.
  - The sweep now builds handlers as startup does (`register_all` with this project's config). A default-constructed `plan_number_helper` is inert, so the old sweep swept its quadratic regex vacuously.
  - RED against the pre-`10fce785e` regexes: `LspEnforcementHandler` 49x, `PlanNumberHelperHandler` 68x. Green maximum across three runs: 13.6x.
- **Item 4** (revert `_KNOWN_CONSTANT_FACTOR_BOUNDS`): `12df23f75`.
  - Removed. Every SAFETY handler has the unwidened 5 s bound, now in thread CPU time.
  - main passes it: `SecretFileGuardHandler` measured 1.06-1.52 s. The branch measured 1.56-2.16 s before the fix and 0.90-1.08 s after.
  - The fix: `secret_file_guard` re-derived candidate paths (a relpath each) per pattern per token. `first_matching_glob` does it once per token.
- **Item 5**: `b1c987623`. The `DISPATCH_TEST_*` constants moved to `tests/dispatch_timeouts.py` as `DispatchTestTimeout`, and every use moved with them.
- **Item 6** (skips): the 70 test files touched on this branch since `c27e826d` contain no `skip`, `skipif`, `xfail`, `importorskip` or `skipTest`, and no root, uid, CI or platform condition.

## Also removed: wall-clock asserts in touched files

Every `elapsed < N` assertion in `test_bounded_dispatch.py`, `test_chain.py`, `test_n34_deadline_probe_isolated_daemon.py` and `test_path_exclusion.py` is gone.

- Most are now ordering proofs: the callable blocks on an Event that is released only after `run()`/`execute()` has returned, or a refused call is shown never to have run.
- The rest are growth ratios. `path_exclusion`'s are RED 87x/51x against main's backtracking matcher.

## For the coordinator

- `CLAUDE_HOOKS_SOCKET_TIMEOUT` is a client-side environment override the daemon cannot see, so `chain_deadline_problems` cannot check it. Lowering it below the deadline makes the python rung deny PreToolUse with `socket_timeout`, not allow, and that deny now names the variable (`e6a80b0c5`).
- Verification after the P1/P2 round: `tests/unit/daemon/`, `tests/unit/install/`, `test_parallel_start_reuse.py` and `test_config_integration.py` gave 3598 passed and 1 skipped (the skip is not in a touched file). Every `tests/integration/test_init_sh_*.py` and `test_forwarder_*.py` passed (165). ruff, black and mypy are clean on the changed files. The daemon was restarted and is healthy with 31/31 per-event listeners. This is not the full suite; the gate is the reviewer's.
- Release note 44 is new. Numbering collisions, if any, are left for merge.
