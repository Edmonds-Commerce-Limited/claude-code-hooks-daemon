# Issue #124 implementer report (Plan 00533, Tasks 1.1 to 1.4 and 2.1)

Branch `worktree-issue-124-dispatch-saturation`. The brief was achievable as written; nothing in it
was wrong. Two design choices go beyond its literal wording and are called out under "Decisions".

## What changed

### Task 1.1: the recovery command through a saturated pool

- **Daemon side.** `utils/cli_command.py` gains `is_install_recovery_command(hook_input, project, install_root)` and `is_recovery_command(hook_input)`, a Python twin of `init.sh`'s
  `_is_daemon_recovery_command` (same spellings, same six subcommands, same space/tab-only padding,
  same `isprintable`, same resolved-launcher check). `DaemonController.process_event` passes
  `capacity_exempt=True` through `EventRouter.route` and `HandlerChain.execute` to
  `BoundedDispatcher.run` for a PreToolUse call that matches. An exempt call takes no slot and skips
  both the in-flight and straggler caps, but it still runs the guards and its deadline still
  applies. Its permit is a no-op (`_SinglePermit(None)`), so it never over-releases the
  `BoundedSemaphore`.
- **Client side.** `init.sh` now has a pinned copy `_DISPATCH_SATURATED_REASON`, equal to
  `core.chain.DISPATCH_SATURATED_REASON` (`chain: not judged in time (dispatch pool saturated)`), and
  `_is_saturation_deny(text)`. On the success path, a PreToolUse deny whose reason starts with that
  string, for the exact recovery command, is sent through `fail('dispatch_saturated', ...)`. That
  lands in the existing carve-out arm, which allows the call and adds context. A guard's own judged
  deny of the recovery command still stands. `.claude/init.sh` is a symlink to `init.sh`, so only
  one file was edited.
- What counts as a recovery command is unchanged.

### Task 1.2: configurable `max_inflight` and a bounded wait for a slot

- `ChainConfig.max_inflight` (int, >= 1, default `DISPATCH_MAX_INFLIGHT` = 16) and
  `ChainConfig.slot_wait_seconds` (float, >= 0, below `CHAIN_DEADLINE_DEFAULT`; default
  `Timeout.DISPATCH_SLOT_WAIT_SECONDS` = 2.0).
- `BoundedDispatcher.run` acquires with `timeout=min(slot_wait, call timeout)` and then refuses as
  before. The wait is subtracted from the call's own timeout, so a chain never gets more than its
  deadline in total.
- `configure_default_dispatcher()` is called from `DaemonController.initialise`.

### Task 1.3: the sustained-saturation WARNING

`BoundedDispatcher._note_saturated` tracks the current refusal episode, which a successful acquire
ends. Once an episode reaches `DISPATCH_SATURATION_WARN_AFTER_SECONDS` (10s) it logs one WARNING:
`Dispatch pool saturated for Ns: X of Y slots in flight, Z straggler(s); ...`. It repeats at most
every `DISPATCH_SATURATION_WARN_INTERVAL_SECONDS` (30s). It is logging only. The clock is
injectable, so the tests do not sleep.

### Task 1.4: the SIGTERM grace exceeds the drain

- `Timeout.DAEMON_ACTIVE_REQUEST_DRAIN` = 5 (with `_POLL` = 0.1).
- `DAEMON_SIGTERM_GRACE` = drain + `DAEMON_SHUTDOWN_AFTER_DRAIN_MARGIN` (3), so 8s.
- `server.py`'s shutdown drain loops on the named budget instead of `range(50)`.
- `cli.py` `cmd_stop` passes `grace_seconds=Timeout.DAEMON_SIGTERM_GRACE`, and its KILLED message
  now names that value.
- Grace (8) + SIGKILL grace (2) still fits `DAEMON_SHUTDOWN` (10), and a test pins that.

### Task 2.1: release note and docs

- `CLAUDE/UPGRADES/UNRELEASED/release-notes/002-a-saturated-daemon-can-be-restarted-from-inside-a-session.md`
- `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.71.0.yaml`, both keys `added`, with the target
  version for the release agent to confirm.
- `docs/guides/CONFIGURATION.md`: two table rows and a new "Dispatch Capacity" section beside
  "Chain Deadline".

## Not changed (out of scope)

- How `chain.py` treats a refused Stop/SubagentStop chain is unchanged: it still fails closed.
- The shipped default of 16 is unchanged.
- No watchdog action, upgrade handover change or persistent log.
- Task 2.2 (filing the follow-up plans) is left to the coordinator.

## Decisions worth a second look

1. **Daemon-side "allow" means "judge without a slot", not a bare allow.** The ruling says
   "never need a permit". Running the chain capacity-exempt keeps every guard's verdict on the
   recovery command, which matches how it is treated when the pool is not full. A bare allow would
   skip guards that never asked to be skipped.
2. **Exempt calls are not counted.** A loop that spammed the exact restart command could start
   unbounded exempt threads, though each one is bounded by its deadline. I judged a cap unneeded
   (YAGNI), since the command is exact and restarts the daemon anyway.
3. **hooks-relay is not covered client-side.** The relay passes a well-formed deny through
   unchanged and only hands off to `init.sh` on an exchange failure. A relay-rung client talking to
   an older, saturated daemon therefore still sees the deny. The daemon-side fix covers any daemon
   built from this branch. A relay twin of the client change would need Rust, so I left it out.
4. The per-refusal WARNING in `_take_slot` that already existed stays, and it is not rate-limited.
   Under sustained load that line still repeats on every refusal; the new episode WARNING is the
   one to look for.

## TDD evidence (red before green)

- Dispatcher tests (`tests/unit/core/test_bounded_dispatch.py`):
  `ImportError: cannot import name 'configure_default_dispatcher' from 'claude_code_hooks_daemon.core.bounded_dispatch'`
- Config, matcher and controller tests: 33 failed, 77 passed. Examples:
  - `AttributeError: module 'claude_code_hooks_daemon.utils.cli_command' has no attribute 'is_install_recovery_command'` (25 cases)
  - `pydantic ... extra_forbidden` for `max_inflight` / `slot_wait_seconds`
- `init.sh` tests: 2 failed. `TestASaturationDenyOfTheRecoveryCommandIsATransportFailure::test_the_recovery_command_is_not_denied`
  failed with `AssertionError: {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', ...}`,
  and the pinned-copy test failed on `assert "_DISPATCH_SATURATED_REASON = ..." in init.sh`. The 10
  init.sh/daemon parity cases passed on the first run, which confirms the Python twin agrees with
  `init.sh`.
- Task 1.4: `test_the_sigterm_grace_is_the_named_one` failed with `assert 5 == 8`, and
  `test_the_active_request_drain_is_the_named_budget` failed with `AssertionError: 5.0127... < 2.0`
  (the drain ignored the budget).

## Green

- `test_chain_config.py`, `test_cli_command.py`, `test_controller.py`, `test_bounded_dispatch.py`,
  `test_chain.py`, `test_router.py`: 380 passed.
- `tests/integration/test_init_sh_pretooluse_fail_closed.py`: 194 passed.
- `tests/unit/daemon/test_cli_commands.py` + `tests/daemon/test_server.py`: 135 passed.
- `test_chain.py`'s `_BogusOutcomeDispatcher.run` test double gained the new keyword.

## Targeted QA

`./scripts/qa/llm_qa.py changed --allow-unmapped` on `ba4b142e5`: **QA: 40/40 PASSED**.
`changed_tests`: 7716 passed, 0 failed, 56 skipped, 124 test files from 22 changed files.

The first run, without `--allow-unmapped`, found three problems, all fixed in `ba4b142e5`:

- `format`: black reformatted the `slot_wait_seconds` annotation in `config/models.py`.
- `error_hiding` (return-none-on-error): `_installs_launcher` caught `OSError`/`ValueError` and
  returned None. Its paths are the daemon's own, never hook input, so it now fails fast, the same
  as `install_recovery_command`. Hook-input paths are still guarded, in `_runs`.
- `changed_tests` unmapped: importing `core.bounded_dispatch` into `config/models.py` made the
  dispatcher reachable from config, which turned it into a too-broad file. The pool-size default
  now lives in `Timeout.DISPATCH_MAX_INFLIGHT`, and `bounded_dispatch.DISPATCH_MAX_INFLIGHT`
  aliases it.

Nine files remain unmapped as too-broad, so the coordinator's full gate must cover them: `init.sh`,
`config/models.py`, `constants/timeout.py`, `core/chain.py`, `core/router.py`, `daemon/cli.py`,
`daemon/controller.py`, `daemon/server.py` and `utils/cli_command.py`. The targeted test files listed
under "Green" above cover each change directly. The daemon was not restarted, per the brief.

## Review fixes

All four review findings were fixed with a red test first. None was disputed. Stop/SubagentStop
semantics, the default of 16 and what counts as a recovery command are all unchanged.

1. **The saturation warning fires under churn.** Only a quiet period ends an episode now:
   `Timeout.DISPATCH_SATURATION_QUIET_SECONDS` (5s) with no refusal. A successful acquire no
   longer ends it. Straggler-cap refusals and last-moment refusals (finding 3) call
   `_note_saturated` too. The message reports refusals since the last report and over what
   window: `Dispatch pool saturated for 10s: 11 call(s) refused in the last 10s, with max_inflight N and S straggler(s) of at most M; ...`. Red:
   `test_a_slot_won_between_refusals_does_not_end_the_episode`: `assert 0 == 1`;
   `test_straggler_cap_refusals_feed_the_same_signal`: `assert 0 == 1`; the message test failed on
   `assert 'for 10s: 11 call(s) refused in the last 10...`.
2. **Exempt calls are bounded.** They use their own `BoundedSemaphore`
   (`Timeout.DISPATCH_EXEMPT_MAX_INFLIGHT` = 2, the `max_exempt_inflight` constructor argument, not
   a config key). An exempt call that times out keeps its slot until its worker finishes, so that
   slot bounds exempt stragglers. A refused exempt call returns `DispatchSaturated`, and init.sh's
   carve-out still lets the exact recovery command through that deny. Red:
   `AttributeError: 'BoundedDispatcher' object has no attribute 'max_exempt_inflight'` and
   `TypeError: ... unexpected keyword argument 'max_exempt_inflight'`.
3. **A slot won too late is refused.** Acquire is tried without blocking first, so the
   uncontended path does not change. A slot won only after waiting, with less than
   `Timeout.DISPATCH_MIN_RUN_SECONDS` (0.1s) of the budget left, is released at once and the call
   gets `DispatchSaturated`. Red: `test_a_slot_won_with_no_time_left_to_run_in_is_refused`:
   `assert False` (on `isinstance(outcome, DispatchSaturated)`), using a semaphore double whose slot
   frees exactly as the wait ends.
4. **The recovery matcher no longer raises, and is cheap.** `is_install_recovery_command` compares
   the text first. Only on a text match does `_runs_installs_launcher` resolve paths, and it
   returns False on `OSError`/`ValueError`, as init.sh does. Red:
   `test_a_command_that_is_not_a_recovery_spelling_resolves_no_path`:
   `AssertionError: assert [PosixPath('/...is_not_a_r0')] == []`;
   `test_a_path_that_cannot_be_resolved_is_not_exempt`: `OSError: unreadable` /
   `ValueError: embedded null byte`. The new parity case
   `test_both_exempt_nothing_when_the_root_cannot_be_resolved` uses a daemon root with a
   300-character component. init.sh said not exempt, and the daemon raised
   `OSError: [Errno 36] File name too long`.

Docs: the Dispatch Capacity section of `docs/guides/CONFIGURATION.md` and release note 002 now
describe the exempt pool and the new warning.

Targeted QA: `./scripts/qa/llm_qa.py changed --allow-unmapped` on a still tree: **QA: 40/40
PASSED**. `changed_tests`: 7725 passed, 0 failed, 56 skipped. The same nine files are unmapped as
too-broad, so the coordinator's full gate must cover them. The daemon was not restarted.

## Full-gate fixes

The full gate on the combined head b4e83885c (this branch at 9f3eff5fd plus N516/N517 on main)
passed 42 of 43 checks; `tests` had 6 failed and 10 errored. A classifier agent ran each failing
test on the combined head and on `main`; the coordinator applied fix 1 (the classifier's own edit
was denied by the cross-worktree write guard, as it was launched in the integration worktree).

1. **Caused by this branch**: `test_hook_input_field_single_source` was red on 9f3eff5fd
   (`utils/cli_command.py:336; :338; :347` read payload fields as raw literals). Fixed to
   `HookInputField.TOOL_NAME`, `.TOOL_INPUT` and `.CWD`. After the fix: that test, `test_cli_command`
   and `test_bounded_dispatch` 111 passed; `tests/integration/test_init_sh_pretooluse_fail_closed.py`
   (the shell parity test) 195 passed; ruff, black and mypy clean on the file.
2. **Environmental**: `test_safety_handlers_hostile_input_performance[deep_eval_nesting]` failed on
   the py3.12 leg only (`block-ancestry-severing-merge` "160x for 8x input"); 5/5 isolated runs pass
   on both the combined head and `main`, and neither branch touches that handler or Bash parsing.
3. **Pre-existing, worktree artefact**: playbook probe #119 (rsync from a worktree into the main
   checkout) is denied by `project_containment` (priority 14) before `worktree_file_copy` (15)
   whenever the project root is a worktree; `main`'s own code reproduces it, and `main`'s checkout
   passes. Neither branch touches either handler or the order.
4. **Environmental**: the py3.11 acceptance leg's 10 "Daemon not running" errors; with a live daemon
   the same tests run (9 pass, the 10th is item 3). The py3.12 and py3.13 legs reached a daemon.

Items 2 to 4 are filed in ledger 00474 by the coordinator.
