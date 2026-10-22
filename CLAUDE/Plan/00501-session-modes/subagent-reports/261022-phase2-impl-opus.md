# Plan 00501 Phase 2 implementation report and handoff (Opus sub-agent)

Worktree `/workspace/untracked/worktrees/worktree-501-phase2-blocked`, branch `worktree-501-phase2-blocked`
(pushed). Head at handoff: `3bfaa6a1b` (Task 2.1). Tasks 2.2 and 2.3 are NOT started: this agent passed its soft
context budget (the injected CLAUDE.md guidance alone is large) and stopped at the Task 2.1 boundary. Targeted QA
has NOT been run (run it once after 2.3, as the brief says). No release note yet (Phase 2 changes behaviour, so the
next agent adds one; check origin/main for the next free number).

## Environment notes

- The worktree venv is `untracked/venv-*/bin/python` (`P=$(ls untracked/venv-*/bin/python)`); it imports the
  worktree's `src` (verified).
- Run pytest with `-p no:cacheprovider`; add `--no-cov` for a quick red run (a scoped `--cov` run exits 1 on the
  global fail-under even when every test passes; read the module's own coverage line instead).
- Black: `$P -m black -q <files>` (the Python 3.11 safety warning is benign). Commits must chain with `&&`.
- Recursive greps over `tests/` need `--exclude-dir=cyber-flag`. A `class X`/`def x` grep is denied once by the
  LSP guard; an identical retry is allowed.

## Task 2.1: delivered (commit `3bfaa6a1b`)

`handlers/user_prompt_submit/failsafe_cron_blockage_suppressor.py`: a prompt with no tick sentinel now goes through
`_note_untagged_prompt`. It clears nothing unless `is_genuine_human_prompt(prompt)` (so a `🤖 [ccy-supervisor` line or
other machine traffic is not the owner, logged at INFO), clears the marker only when the marker's `session_id` is
this session (another session's prompt is logged at INFO and keeps it), and resets the cadence only when the
cadence record is absent or belongs to this session.

Tests: `TestOnlyTheSameSessionsHumanClears` in
`tests/unit/handlers/user_prompt_submit/test_failsafe_cron_blockage_suppressor.py` (another session's prompt keeps the
marker and the next tick is still dropped; a supervisor line keeps the marker and the tick is dropped; the same
session's human still clears; a supervisor line keeps the cadence; another session's prompt keeps the cadence).

- RED (`untracked/scratch/p2-red-21.txt`): 3 failed, 1 passed (`AssertionError: assert None is not None`: the marker
  or cadence had been cleared).
- GREEN: `tests/unit/handlers/user_prompt_submit/` 364 passed. The new code is fully covered; the module's remaining
  uncovered lines (278-292, 422-427, 508, 556-558) are pre-existing. ruff, mypy --strict clean.

## Task 2.2: design for the next agent (TDD; tests first)

Code found (all in the worktree):

- Writer: `handlers/stop/auto_continue_stop.py` `_maybe_record_human_blocked_marker` (about line 987) calls
  `blockage_marker.write_marker`; on True, `handle()` Branch 2 calls `_stand_in_block` (about line 714).
- Readers of the legacy marker: the suppressor (above) and `handlers/stop/idle_workable_issue_stop_gate.py`
  `_awaiting_human` (about line 224). `utils/cron_pause.py` only reuses `marker_is_valid`'s rule (leave it).
- Registry: `get_data_layer().session_modes` (`core/session_mode_registry.py`); helpers
  `pin_session_modes`/`awaiting_human_entry` in `tests/support/autonomy.py`.

Steps:

1. `auto_continue_stop`: on a declared stop, `enter` a `SessionModeEntry(mode=BLOCKED, reason=DECLARED, source=AGENT, lifetime=SESSION, expires_at=now + 24 h)` (24 h is the suppressor's `expiry_hours` default; keep one
   constant). An `OSError` from the registry write must not be swallowed at DEBUG: log at WARNING via
   `log_and_continue` and report `marker_written=False` in `stop-events.jsonl`. Decide with the coordinator whether
   to keep writing the legacy file too during the transition (recommended: stop writing it, import it once).
2. **Mandatory stand-in exemption.** `_stand_in_block` gates on `autonomy_allowed(hook_input)`, which becomes False
   as soon as the awaiting-human mode exists, so R-STOP-STAND-IN-MISSING would silently stop firing. Gate it on
   `autonomy_verdict(hook_input).environment_allowed` and on the policy having no focus (`policy.focus_task is None`), i.e. ignore the BLOCKED label for this one demand. Test: the mode is recorded AND the stand-in deny
   still fires for that stop (and still does not fire in a desktop `containers-only` environment, nor under focus).
   Existing tests: `tests/unit/handlers/stop/test_auto_continue_stop_stand_in.py`,
   `test_auto_continue_stop_autonomy.py`.
3. Legacy import, once: when the registry loads (or on the suppressor's first read), a valid
   `human-input-blockage-marker.json` becomes a BLOCKED(declared) entry for its session with
   `expires_at = recorded_at + 24 h`, then the file is deleted. An expired or corrupt one is logged and deleted.
   Test it imports once and a second load does not re-import.
4. The suppressor reads the policy: replace `marker_is_valid` with `registry.policy(session_id).tick_action(tick, runs_while_blocked=..., work_owed=...)` (Phase 1's truth table matches today's rows 2/3 and the declared-job rule).
   The Task 2.1 clear becomes `registry.exit(session_id, ModeLabel.AWAITING_HUMAN)` (and GOAL_BLOCKED) on a genuine
   prompt in that session; the cross-session and supervisor-line tests from 2.1 must keep passing unchanged.
   `matches()` currently keys on the marker file existing; it must instead match any genuine prompt whose session
   has a registry mode or cadence record. Move `idle_workable_issue_stop_gate._awaiting_human` to the policy too.
5. Ruling 07 (post-compact `continue` suppressed under BLOCKED, `/compact` still runs, logged as a named noop
   reason): the `continue` is typed by the supervisor (`.claude/ccy/claude-supervise.py`, `WOULD_CONTINUE`), which
   this brief forbids touching, and the plan schedules it as Phase 5 Task 5.1 (supervisor reads the
   `<stem>.session-modes` file). The daemon side of Phase 2 is that the BLOCKED mode is written to that file.
   Next agent: check `handlers/pre_compact/compaction_signal.py` for a daemon-owned signal the supervisor already
   reads for the post-compact continue; if none, report to the coordinator that Ruling 07 lands in Task 5.1.

## Task 2.3: design

`core/mode_interceptor.py` `UnattendedModeInterceptor` (wired in `daemon/controller.py`) blocks every main-thread
Stop before the chain. Make it stand down when `hook_is_usage_paused(hook_input)` or when the session policy's
`unattended_block_applies` is False (BLOCKED either reason; focus does NOT stand it down). Tests: usage-paused,
awaiting-human and goal-blocked each allow the stop; focus and no mode still block; another session's mode changes
nothing.

## Second agent (Task 2.2): Ruling 07 settled, the rest designed and not built

This agent went past the soft context budget before writing any code: the injected guidance is about 60k tokens on
its own. It settled Ruling 07 and pinned the open design decisions below, then committed and stopped. No production
or test code was changed, so there is no red/green evidence yet. Task 2.2 is NOT ticked.

### Ruling 07: no daemon lever, so it moves to Task 5.1 (recorded in PLAN.md under Task 2.2)

`handlers/pre_compact/compaction_signal.py` writes `<stem>.compacting` at PreCompact. The supervisor decides
`WOULD_CONTINUE` from `reading.compacting`, which comes from that signal OR from the context sidecar's own
`compacting` field (`claude-supervise.py` about line 2649, and 7215-7240). Withholding the signal under BLOCKED would
therefore not reliably stop the `continue`. It would also leave the supervisor's AWAIT_COMPACTING wait after a
`/compact` it typed without the signal it needs, so the wait times out, and failed injections keep counting towards
`max_injections` (the reset happens only on a confirmed compaction, about line 6300). Neither is a small, safe
change. Task 5.1 already names the `WOULD_CONTINUE` skip, so the daemon's whole part of Ruling 07 is the BLOCKED entry
in `<stem>.session-modes`, which Task 2.2 step 1 writes.

### Decisions pinned for the next agent (they refine steps 1-4 above)

- **Constants** (`utils/session_modes.py`): add `DECLARED_BLOCKED_TTL_SECONDS = 24 h`, a `BLOCKED_LABELS` frozenset
  (AWAITING_HUMAN, GOAL_BLOCKED), a `SessionPolicy.is_blocked` property, and a `declared_blocked_entry(session_id, *, entered_at)` factory (BLOCKED, DECLARED, AGENT, SESSION lifetime, expires `entered_at + TTL`). The writer, the
  legacy import and the tests all use this one factory.

- **Expiry options**: the suppressor's `expiry_hours` and the idle gate's `marker_expiry_hours` stop meaning anything,
  because expiry now lives in the entry. Remove both attributes (`_expiry_hours`, `_marker_expiry_hours`,
  `DEFAULT_MARKER_EXPIRY_HOURS`). Update `docs/guides/HANDLER_REFERENCE.md` (about line 4737) and say so in the
  release note. This repository's own `.claude/hooks-daemon.yaml` sets neither option.

- **Legacy import**: add `import_legacy_blockage_marker(registry, marker_path) -> bool` in
  `core/session_mode_registry.py`. It uses `blockage_marker.read_marker`. Check `exists()` first, so that a corrupt
  file is told apart from a missing one: corrupt means a WARNING and delete. A live marker becomes
  `declared_blocked_entry(entered_at=recorded_at)`; an expired or future-dated one is logged at INFO and deleted. In
  every case the file is unlinked. Call it in `DaemonDataLayer.session_modes` right after `registry.load()`, with
  `ProjectContext.daemon_untracked_dir() / MARKER_FILENAME`. The data layer builds the registry once and the file is
  deleted, so a second load never re-imports. Test both cases in `tests/unit/core/test_session_mode_registry.py` and
  `test_data_layer.py`.

- **Writer** (`auto_continue_stop._maybe_record_human_blocked_marker`, about line 987): stop writing the legacy file
  and call `get_data_layer().session_modes.enter(declared_blocked_entry(...))`. A RuntimeError (no project context)
  and an OSError both go through `log_and_continue` at WARNING (the RuntimeError is DEBUG today; raise it) and
  return False. Keep the stop-events key `marker_written`.

- **Stand-in exemption** (`_stand_in_block`, about line 722): replace `autonomy_allowed` with
  `v = autonomy_verdict(hook_input)` and return None when `not v.environment_allowed or v.session.focus_task is not None`. Tests in `test_auto_continue_stop_stand_in.py`: after the stop, (a) the registry holds AWAITING_HUMAN and
  the deny still fires; (b) a desktop `containers-only` stop gives no deny (`pin_desktop_containers_only`); (c) a
  stop under focus (`focus_entry`) gives no deny. The goal-ledger challenge (about line 970) keeps
  `autonomy_allowed`, so it is suppressed while BLOCKED, as the plan's "No re-arm" requires.

- **Suppressor**: add a `_policy(session_id)` helper that reads `get_data_layer().session_modes.policy(...)`. On
  RuntimeError or OSError it logs a WARNING and returns an empty policy, so the tick is delivered. Compute
  `failsafe = tick or DaemonTick(TickKind.FAILSAFE)` (this covers the pre-sentinel heading) and then
  `action = policy.tick_action(failsafe, runs_while_blocked=False, work_owed=owed)`:

  - DROP means row 3: deny with `_RULE`.
  - THIN means row 2: `_apply_backoff`.
  - Anything else falls to rows 1 and 4.

  For other ticks, `runs` is true only when the tick is DECLARED, `policy.is_blocked` holds and the config says
  `runs_while_awaiting_human`. DROP then denies with `_DECLARED_RULE`. Focus wording for a dropped declared tick is
  Task 3.2's job. `_note_untagged_prompt` exits AWAITING_HUMAN and GOAL_BLOCKED for this session. An OSError there
  is a WARNING, and the prompt is still allowed. `matches()` returns True when the canonical marker is present, or
  a cadence file exists, or `_policy(session).is_blocked`.

- **Idle gate** `_awaiting_human` (about line 224): `session_policy(hook_input).is_blocked`, or this stop declares
  it.

- **Test isolation (do this first)**: `tests/conftest.py` never resets the data-layer singleton. A registry built in
  one test therefore stays bound to that test's tmp dir. Add an autouse fixture:
  `monkeypatch.setattr(data_layer.get_data_layer(), "_session_modes", None)`.

- **Tests to migrate** off `write_marker`/`MARKER_FILENAME` (the suppressor's tests use fake clocks of about 1000 s,
  which the registry's real clock reads as expired, so use `pin_session_modes` + `awaiting_human_entry`):

  - `test_failsafe_cron_blockage_suppressor.py` (21 sites; the Task 2.1 tests become registry assertions with the
    same scenarios);
  - `test_failsafe_cron_multi_cron_ticks.py`;
  - `test_auto_continue_stop.py` (10);
  - `test_auto_continue_stop_stand_in.py` (6);
  - `test_awaiting_human_marker_scope.py`;
  - `test_idle_workable_issue_stop_gate.py`;
  - `tests/integration/test_handlers_do_not_match_prose.py`.

  `utils/cron_pause.py` uses only `marker_is_valid`; leave it as it is.

## QA

Not run yet.

## Left

Tasks 2.2 and 2.3, the release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, PLAN.md ticks for 2.2/2.3,
targeted QA, and filling in this report's QA section with the QA line, head sha and unmapped files.

## Third agent (Task 2.2 part A): built, not ticked

Built, test-first:

- `tests/conftest.py`: autouse `no_session_modes_registry_outlives_a_test` sets the singleton's `_session_modes`
  to None for every test.
- `utils/session_modes.py`: `DECLARED_BLOCKED_TTL_SECONDS` (24 h), `BLOCKED_LABELS`, `SessionPolicy.is_blocked`,
  `declared_blocked_entry(session_id, *, entered_at)`.
- `core/session_mode_registry.py`: `SessionModeRegistry.now()` (the registry clock) and
  `import_legacy_blockage_marker(registry, marker_path)`. A live marker is imported. An expired, future-dated or
  blank-session marker is logged at INFO. A corrupt one is logged at WARNING. The file is deleted after it is
  judged. If `enter` raises OSError, the exception propagates and the file stays.
  `DaemonDataLayer.session_modes` calls the import after `load()`.
- `auto_continue_stop._maybe_record_human_blocked_marker` now calls `session_modes.enter(declared_blocked_entry(...))`.
  RuntimeError and OSError are logged at WARNING and return False. It no longer writes the legacy file. Only DECLARED
  (awaiting-human) is written here, because no stop declares goal-blocked.
- `_stand_in_block` now uses `autonomy_verdict` (it returns None when the environment is not allowed or focus is on).
  This step from part B had to come in early: once the stop writes BLOCKED, `autonomy_allowed` went False and the
  stand-in deny stopped firing (5 stand-in tests went red).
- Removed the `_expiry_hours`, `_DEFAULT_EXPIRY_HOURS`, `_marker_expiry_hours` and `DEFAULT_MARKER_EXPIRY_HOURS`
  attributes and constants. Both handlers use `DECLARED_BLOCKED_TTL_SECONDS` for now. `HANDLER_REFERENCE.md` and the
  idle gate's explainer are updated.
- These tests now check the registry instead of the legacy marker file: `test_auto_continue_stop.py`,
  `test_auto_continue_stop_stand_in.py` (3 asserts), `test_awaiting_human_marker_scope.py` (the single-writer check
  now looks for `declared_blocked_entry` calls), and `tests/integration/test_handlers_do_not_match_prose.py`
  (`_arms_suppression`).

Red: `untracked/scratch/p2a-red.txt` in the worktree (3 import errors at collection, then 7 failed / 150 passed).
Green: `untracked/scratch/p2a-green.txt` (999 passed across `tests/unit/handlers/stop/`, `user_prompt_submit/`,
the session-modes, registry, data-layer and autonomy tests, and the prose integration test). mypy is clean on
`src/` (757 files) and ruff is clean on the touched files. The commit sha is in the commit that adds this section
(`git log -1 -- <this file>`).

**Interim state, so merge only after part B**: the stop now writes only the registry, but the suppressor and the
idle gate still read the legacy marker file. On this branch a declared awaiting-human therefore drops no ticks yet.

Part B must:

1. Suppressor: add the `_policy(session_id)` helper, compute `tick_action`, and send `_note_untagged_prompt` exits
   through the registry, as pinned above. Migrate `test_failsafe_cron_blockage_suppressor.py` and
   `test_failsafe_cron_multi_cron_ticks.py` to `pin_session_modes` + `awaiting_human_entry`. The
   `TestStandInTickDelivered` cases in `test_auto_continue_stop_stand_in.py` still use `write_marker` and also need
   migrating.
2. Idle gate `_awaiting_human`: `session_policy(hook_input).is_blocked`, or this stop declares it. Migrate
   `test_idle_workable_issue_stop_gate.py`.
3. Add the stand-in tests (b) desktop `containers-only` gives no deny, and (c) focus gives no deny. The code is in
   place, the tests are not.
4. Delete the now-unused `write_marker` / `marker_is_valid` callers' imports. Keep `blockage_marker` for `read_marker`
   (used by the import) and `cron_pause`.
5. Write the release note (expiry options removed, legacy marker imported once), tick 2.2, and run targeted QA.
