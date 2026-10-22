# Plan 00501 Phase 6 (goal-loop detector): handoff from the first agent

Brief: `untracked/scratch/brief-501-phase6.md`. Worktree `/workspace/untracked/worktrees/worktree-501-phase6-goal-loop`,
branch `worktree-501-phase6-goal-loop`, base `f8a3a36a0`. **No code was written.** The agent passed its 150k soft context
budget on reading alone, because the injected CLAUDE.md guidance is about 60k tokens on its own. Tasks 6.1 to 6.4 are not
ticked. Nothing is merged, and the daemon was not restarted.

Advice to the coordinator: split Phase 6 across at least two agents (6.1 + 6.2 observe, then 6.3 + 6.4 + note + QA).
Give each one this file instead of the reading list.

## Facts established (already read, so the next agent does not need to re-read them)

- **Registry**: `core/session_mode_registry.py`.
  - `enter(entry, evidence=)`, `exit(session_id, label, evidence=)`, `policy()`, `now()`, `transition_log`.
  - Expiry is lazy and logs `TransitionAction.EXPIRE` itself, so the **4-hour timer is just `expires_at`**.
  - Access it through `get_data_layer().session_modes`. That raises `RuntimeError` (no ProjectContext) or `OSError`.
- **Entry model**: `utils/session_modes.py`.
  - `SessionModeEntry(mode=BLOCKED, reason=BlockReason.GOAL_LOOP, source=ModeSource.DETECTOR, lifetime=SESSION, ...)`
    gives the label `GOAL_BLOCKED`.
  - Add a `goal_loop_blocked_entry(session_id, *, entered_at, ttl_seconds)` factory, next to `declared_blocked_entry`.
  - `is_genuine_human_prompt(text)` is the prompt classifier to reuse for transcript user records.
- **Transition log**: `core/session_mode_log.py`.
  - `ModeTransition(at, session_id, label, action, evidence, detail)`.
  - `TransitionAction` is a closed StrEnum: enter/exit/expire/restart-clear.
  - For observe-mode near misses and would-fire records, add `NEAR_MISS = "near-miss"` and `WOULD_ENTER = "would-enter"`.
    `from_record` validates through the enum, so old logs still parse.
  - Append through `registry.transition_log.append([...])`. Put the evidence (counts, window, similarities, fingerprints,
    thresholds, exit cause) in `evidence` as compact `k=v` text.
- **Human-prompt exit already exists.** `handlers/user_prompt_submit/failsafe_cron_blockage_suppressor._note_untagged_prompt`
  exits every `BLOCKED_LABELS` label (GOAL_BLOCKED included) on a genuine prompt from the same session, with evidence. Task
  6.4 needs only a test that pins it for GOAL_BLOCKED, plus the detector resetting its own ring when the transcript shows a
  genuine human prompt.
- **Goal clear**: `daemon/session_mode_ipc.clear_goal_signal(session_id)`. It defers the `goal_injection` import, because
  importing that directly causes an import cycle. It returns False on failure and has already logged it. The supervisor
  already honours BLOCKED and the goal-clear signal (Phase 5), so **no supervisor change is needed**.
- **Focus-entry precedent**: `core/focus_mode.enter_focus` shows the shape of "enter, clear the goal once, one line stating
  the result". Mirror it for goal-loop entry, including the wording for a failed clear.
- **Spike 0.2 record shapes**:
  - Count `type:"attachment"` records with `attachment.type=="goal_status"`, `met:false` and NO `sentinel`.
  - Ignore `sentinel:true`, which compactions and skill loads also write. A `sentinel:true met:true` record is written by
    a `/goal clear`; treat it as the loop ending, and log it with the cause `goal-cleared`.
  - `type:"user"` with `isMeta:true` ("Stop hook feedback:") is never human.
  - Supervisor lines (`🤖 [ccy-supervisor`) and ticks (`[tick:`) are rejected by `is_genuine_human_prompt` already.
  - A tool_result user record has list content and is not a prompt.
  - The verdict is observed one Stop late (the evaluator runs in parallel), so count cycles on the NEXT Stop's read.
- **Stop handler template**: `handlers/stop/usage_pause_stop_gate.py`. It uses `StopHandlerBase` (`core/handler_bases`),
  `HandlerID`/`Priority` constants and `scope=HandlerScope.MAIN`, and it is non-terminal.
  - Wiring a new handler (the Phase 3 and 4 precedent) means touching: `constants/handlers.py` HandlerID,
    `constants/priority.py`, `.claude/hooks-daemon.yaml` (+ `.example`), `daemon/init_config.py`,
    `docs/guides/HANDLER_REFERENCE.md`, the guidance coverage test, the handler completeness count, and
    `regenerate-docs --project-root` for `.claude/HOOKS-DAEMON.md` and the CLAUDE.md block.
  - Check what result type `StopHandlerBase.handle` allows, and whether a Stop allow can carry a context line. If it
    cannot, deliver the one-time line through a registry notice. Notices are popped by `core/session_mode_statement`
    on the next prompt, and that is the single consumer, so do not add a second one.
- **Declared-stop detection**: reuse `auto_continue_stop`'s existing `[awaiting-human]` and legacy-phrase matcher. Find
  it with LSP from `_maybe_record_human_blocked_marker`. Do not write a second regex.
- **Environment**: venv python `$(ls -d untracked/venv-*/ | awk 'NR==1')bin/python`. Use `-p no:cacheprovider`, and
  `--no-cov` for red runs. Recursive greps need `--exclude-dir=cyber-flag`. The first `class X` grep is denied once by
  the LSP guard. Chain commits with `&&`. The release note number is 024
  (`CLAUDE/UPGRADES/UNRELEASED/release-notes/`).

## Pinned design (recommended; the next agent may refine it, but should state any change)

1. **`core/goal_loop.py`** (pure logic, fully unit-tested on scrubbed fixtures under `tests/fixtures/goal_loop/`). Use
   fake UUIDs and `/workspace/...` paths only.
   - `extract_events(lines) -> list[LoopEvent]`, where a LoopEvent kind is STOP(text, declared), UNMET, GOAL_CLEARED or
     HUMAN, each with its timestamp.
   - `CycleRing`: a deque of cycles `(at, stop_text, declared)`. A cycle is a STOP followed by an UNMET with no HUMAN
     between them. HUMAN or GOAL_CLEARED empties the ring, and the exit cause is logged. Cycles older than the window
     drop out.
   - `threshold = declared_cycle_threshold (2) if every cycle in the window is declared, else cycle_threshold (3)`.
   - Similarity (`difflib.SequenceMatcher` ratio of consecutive stop texts) goes into the evidence only. Include the
     reworded-stops fixture, which must fire at low similarity.
2. **Checkpoint**: per session `(transcript_path, inode, byte_offset)`, kept in memory in the handler. Read only from
   the offset, and advance it only to the last complete newline.
   - A shrunk file or a changed inode resets the offset to 0, logged at INFO.
   - First sight of a session starts at EOF minus a bounded tail, for example 256 KiB. That avoids a full rescan on
     daemon restart and still catches a loop that is under way.
3. **Fingerprint**: compute it only when this read produced an UNMET.
   - Run `git rev-parse HEAD` and `git status --porcelain -uno` in the project root, with a timeout, and drop lines under
     `*/JOURNAL/*` and `untracked/`. Hash the result.
   - A fingerprint different from the ring's means a repo change: empty the ring, cause `repo-change`.
   - In act mode, also exit GOAL_BLOCKED with that evidence.
4. **Config** (handler options, these defaults): `mode: observe` (`observe|act`, anything else is a config error),
   `cycle_threshold: 3`, `declared_cycle_threshold: 2`, `window_minutes: 30`, `blocked_hours: 4`.
5. **observe**: at the threshold, append `WOULD_ENTER` with the full evidence. At threshold-1, append `NEAR_MISS`. Every
   ring reset appends its exit cause. No mode, no clear.
6. **act**: `registry.enter(goal_loop_blocked_entry(...), evidence=...)`, then `clear_goal_signal`, then one line, once
   per entry. No `continue:false`.
   - Document the no-ccy backstop in the handler's `get_claude_md` and in the release note: Claude Code caps a turn at 8
     consecutive stop-hook continuations, the 9th block ends the turn. Each tool call resets the count, and
     `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` raises the cap. After it, Claude Code pauses the goal until the next message,
     which includes a tick. A loop that makes tool calls between stops never reaches the cap.
7. **Exits (6.4)**:
   - human prompt: already exists, see the facts above;
   - repo change: the detector, on the next Stop;
   - timer: `expires_at`, already logged as EXPIRE;
   - explicit clear: add an IPC action `exit_blocked` and `hooks-daemon session-mode unblock`. Follow the `exit_focus`
     pattern and pass the CLI evidence. Test each exit, and test that each is logged with its cause.
8. **Unreadable input**: the detector must never break Stop, so it **stands down** (allows, counts nothing for that
   Stop) and logs a WARNING naming the condition:
   - `goal-loop detector: transcript unreadable <path>: <error>`;
   - `checkpoint invalid, re-anchored at EOF`;
   - `fingerprint failed: <error>`, in which case it does not fire on that Stop.
     A missing `transcript_path` is logged at INFO and stands down.
9. **Latency**: time `handle()` on a synthetic transcript of about 50 MB, both the first sight (bounded tail) and the
   steady state (a few KB per Stop). Also time the git fingerprint separately. State the numbers in the report.

## Left (all of it)

Tasks 6.1 to 6.4 (TDD), the handler wiring and generated docs, release note 024 (observe-only by default), the PLAN.md
ticks, targeted QA
(`FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range f8a3a36a0..HEAD --allow-unmapped`), and the final
report at `CLAUDE/Plan/00501-session-modes/subagent-reports/261022-phase6-impl-opus.md`.

## Part A (6.1 + 6.2): core done, handler NOT yet wired

The second agent went past its 150k soft budget, because the injected guidance alone is about 60k tokens. It stopped at
a clean commit, `473593ba8`. **6.1 and 6.2 are not ticked**, because the Stop wiring, the latency measurement and QA
are still open.

### Done (commit `473593ba8`)

- `src/claude_code_hooks_daemon/core/goal_loop.py` holds the pure logic. mypy --strict is clean. Its public API:
  - `extract_events(lines, *, stop_prefix, declares_blocked) -> Extraction(events, skipped)`. The `EventKind` values
    are STOP, UNMET, GOAL_MET (met:true, no sentinel), GOAL_CLEARED (sentinel met:true) and HUMAN. isMeta records,
    tool_result lists and sentinel met:false snapshots are ignored. A text-only list content counts as a prompt.
  - `read_new_lines(path, checkpoint|None, *, tail_bytes) -> (lines, Checkpoint(path, inode, offset))`.
    - The first sight of a session, and any backlog bigger than `tail_bytes`, reads only the tail, starting from a
      line boundary.
    - A changed path, a changed inode, or a file that shrank raises `CheckpointInvalidError`. Its `.anchor` is a
      checkpoint at EOF.
    - A missing file raises `OSError`.
  - `GoalLoopConfig` defaults: `observe`, 3, 2, 30 min, 4 h. It has `from_options` and `window_seconds`.
    `option_problems(options)` is ready for the handler's `validate_options`.
    - `DetectorMode` has only OBSERVE, so `mode: act` is reported as invalid and withheld. **Part B adds ACT** to the
      enum, which makes `act` valid.
  - `CycleRing(window_seconds=)`:
    - `.feed(events) -> FeedResult(new_cycles, resets)`. A reset is only reported when the ring held at least one
      cycle. Its causes are human-prompt, goal-cleared and goal-met.
    - `.note_fingerprint(fp, new_cycles=) -> RingReset|None` returns cause repo-change. It keeps the newest
      `new_cycles`.
    - A cycle's `at` is the time of the unmet evaluation. The window is measured back from the newest cycle.
  - `assess(ring, config) -> Assessment(verdict QUIET|NEAR_MISS|WOULD_ENTER, count, threshold, declared, similarities, span_seconds)`. `.evidence(config, fingerprint)` builds the compact `k=v` text. Similarity is only
    ever written into the evidence.
  - `repo_fingerprint(root, *, run=run_git, timeout=Timeout.GIT_CONTEXT)` hashes HEAD plus
    `status --porcelain -uno`, with `*/JOURNAL/*` and `untracked/` excluded. It raises `FingerprintError`.
- Fixtures are in `tests/fixtures/goal_loop/*.jsonl`. They were generated by `untracked/scratch/make_goal_loop_fixtures.py`
  (not committed) and use the all-zero placeholder UUID; `sensitive_content` denies any other UUID. The reworded-stops
  fixture reaches WOULD_ENTER with every similarity below 0.6.
- Tests are in `tests/unit/core/test_goal_loop.py`. Red: collection failed with an ImportError because the module did
  not exist. Green: 54 passed.

### Left for part A (do these before part B)

1. **Handler** `handlers/stop/goal_loop_detector.py` (TDD; write `tests/unit/handlers/stop/test_goal_loop_detector.py`
   first):
   - Base it on `StopHandlerBase`, non-terminal, with `scope=HandlerScope.MAIN`.
   - Priority **5**, which is free below the terminal `auto_continue_stop` (10 in this project). Taken: 4, 6, 7, 8
     (project) and 9.
   - Import `_declares_human_blocked` and `_STOP_EXPLANATION_PREFIX` from `auto_continue_stop`;
     `idle_workable_issue_stop_gate` already imports the former, so there is precedent.
   - Keep per-session state (`Checkpoint`, `CycleRing`) in an LRU-bounded OrderedDict.
   - Options arrive as `self._mode`, `self._cycle_threshold` and so on, through `apply_handler_options` (setattr
     `_<key>`). Add `validate_options = staticmethod(option_problems)` in the `bash_safe_mode` style.
   - `handle()` flow:
     - A missing `transcript_path`: log at INFO and allow.
     - `OSError`: WARNING `goal-loop detector: transcript unreadable <path>: <error>`, and allow.
     - `CheckpointInvalidError`: WARNING `checkpoint invalid, re-anchored at EOF`, store the anchor, and allow.
     - Otherwise feed the events, then log every reset to the transition log.
     - When `new_cycles > 0`, run the fingerprint. `FingerprintError` gives WARNING `fingerprint failed: <error>` and
       no assessment on that Stop.
     - Call `note_fingerprint`, logging any reset, then `assess`. NEAR_MISS and WOULD_ENTER are appended with the
       evidence.
     - Always allow.
   - Transitions are `ModeTransition(at, session_id, ModeLabel.GOAL_BLOCKED, action, evidence, detail)`, appended
     through `get_data_layer().session_modes.transition_log` (it may be None). A `RuntimeError` or `OSError` there
     gives a WARNING and never breaks the Stop.
   - Add `NEAR_MISS = "near-miss"`, `WOULD_ENTER = "would-enter"` and `LOOP_RESET = "loop-reset"` to
     `TransitionAction` in `core/session_mode_log.py`, and check for any exhaustive tests over it.
   - Use seams (a fingerprint callable and an append callable) so the tests need no git and no data layer.
2. **Wiring**: follow the list under "Stop handler template" above. Use `HandlerIDMeta(class_name= "GoalLoopDetectorHandler", config_key="goal_loop_detector", display_name="goal-loop-detector")`, then update the
   yaml, the `.example`, `init_config.py`, `HANDLER_REFERENCE.md`, the priority-band tables (HANDLER_DEVELOPMENT.md,
   CONTRIBUTING.md and CONFIGURATION.md, which list the 0-9 Stop handlers), the guidance coverage, the completeness
   count and `regenerate-docs`.
3. **Latency**: time `handle()` on a synthetic transcript of about 50 MB, measuring the first sight, the steady state
   and the fingerprint separately. Run it with the venv python from untracked/scratch.
4. **QA**: run the targeted QA command from the brief, then tick 6.1 and 6.2 and append the numbers here.

## Part A2: the Stop handler wired (6.1 and 6.2)

### What changed

- `handlers/stop/goal_loop_detector.py`: `GoalLoopDetectorHandler`, a `StopHandlerBase` that is non-terminal, uses
  `HandlerScope.MAIN` and has priority 5. It follows the part A `handle()` flow exactly, and it always allows.
  - Per-session `_SessionState(ring, checkpoint)` is kept in an `OrderedDict` LRU, `MAX_TRACKED_SESSIONS = 64`.
    `TAIL_BYTES` is 2 MiB.
  - Options are `_mode`, `_cycle_threshold`, `_declared_cycle_threshold`, `_window_minutes` and `_blocked_hours`. Each
    Stop builds `GoalLoopConfig.from_options`, and `validate_options = staticmethod(option_problems)`.
  - Seams: `_fingerprint_repo` (default `repo_fingerprint(ProjectContext.project_root())`), `_append_transition`
    (default `get_data_layer().session_modes.transition_log.append`, and None is skipped) and `_clock`.
  - Transitions use the label `GOAL_BLOCKED`.
    - `loop-reset` sets `detail` to the cause and the evidence to `cause=<c> dropped=<n>`, at the reset's time.
    - `near-miss` and `would-enter` are logged only on a Stop that added cycles, with `Assessment.evidence`.
  - Named WARNINGs, each prefixed `goal-loop detector:`: `transcript unreadable <path>: <err>`, `checkpoint invalid, re-anchored at EOF`, `fingerprint failed: <err>` (with no assessment on that Stop), and
    `transition not logged (...)` (for `OSError` or `RuntimeError`). A missing `transcript_path` or `session_id` is
    logged at INFO.
  - `get_claude_md()` returns None. It is recorded as exempt in `test_claude_md_guidance_coverage.py`, because it is
    observe-only.
- `TransitionAction` gains `NEAR_MISS`, `WOULD_ENTER` and `LOOP_RESET`. The existing log and registry tests are
  unaffected, since no test is exhaustive over the enum.
- Wiring:
  - `HandlerID.GOAL_LOOP_DETECTOR` and `Priority.GOAL_LOOP_DETECTOR = 5`.
  - The yaml, the `.example` (options commented) and `init_config.py`.
  - A `HANDLER_REFERENCE.md` section, plus the 0-9 band rows in HANDLER_DEVELOPMENT.md, CONTRIBUTING.md and
    CONFIGURATION.md.
  - `_EXPECTED_MAIN` in `test_handler_scope_defaults.py`, and `_VALID_NON_DEFAULTS` in
    `test_registry_option_injection.py`.
  - `regenerate-docs`, which updated HOOKS-DAEMON.md (Stop now lists 7 handlers). The CLAUDE.md block is unchanged.
- **Deviation:** `mode` is NOT a row in the reference's options table. It is mentioned in the prose instead. The reason
  is that `test_registry_option_injection` needs a valid non-default for every declared option, and `observe` is the
  only valid value. **Part B** adds `ACT`, then adds the `mode` row back with `("goal_loop_detector", "mode"): "act"`
  in `_VALID_NON_DEFAULTS`.

### Red/green

- Red: `tests/unit/handlers/stop/test_goal_loop_detector.py` failed at collection with
  `ModuleNotFoundError: ...goal_loop_detector`.
- Green: 26 passed. With `test_session_mode_log.py` and `test_session_mode_registry.py`, 134 passed. mypy --strict is
  clean on the handler and its test.
- A subset of the wiring-sensitive tests (39 integration and daemon files, plus `tests/unit/handlers/test_*.py`,
  `tests/unit/config` and `tests/unit/handlers/stop`) first gave 4 failed and 5420 passed:
  - the guidance verdict;
  - two scope defaults;
  - option injection.
- After those fixes, the three affected files gave 820 passed.

### Latency (`untracked/scratch/goal_loop_latency.py`, worktree venv)

These were measured on a 52,429,110-byte synthetic transcript of 4 KB tool_result lines, with the real
`repo_fingerprint` on this worktree:

| Stop                                        | Added latency                 |
| ------------------------------------------- | ----------------------------- |
| First sight (2 MiB tail read and parse)     | 9.1 ms                        |
| Warm, no new cycle (checkpoint read only)   | median 0.07 ms, max 0.22 ms   |
| Warm, new cycle (read, fingerprint, assess) | median 9.77 ms, max 10.73 ms  |
| `repo_fingerprint` alone (two git calls)    | median 10.27 ms, max 12.75 ms |

On a cycle Stop the cost is dominated by the fingerprint. The first-sight cost is bounded by `TAIL_BYTES`, not by the
transcript's size.

### QA

The first targeted run (`changed --range f8a3a36a0..HEAD --allow-unmapped`) gave
`QA: 36/41 PASSED, 3/41 FAILED`, failing format, lint and error_hiding. Those findings were fixed in `2db729bfb`:

- black reformatting;
- RUF007, by using `itertools.pairwise` in `assess`;
- PTH116, by using `Path.stat` in `test_goal_loop.py`;
- `return-none-on-error`, because `_timestamp` now raises `ValueError` and `extract_events` counts it as skipped;
- `log-and-continue`, because a failed transition append now goes through
  `deliberate_swallow.log_and_continue` with a reason.

The re-run on the clean tree at `77a084b1e` (the code head; only this report line follows it) gave
**`QA: 41/41 PASSED`**, with changed_tests at 6709 passed, 0 failed and 5 skipped, across 97 test files mapped from 25
changed files.

### What part B must know

- Add `DetectorMode.ACT`. Restore the `mode` row in HANDLER_REFERENCE.md and add the `_VALID_NON_DEFAULTS` entry (see
  the deviation above).
- `handle()` has one place to act: the `WOULD_ENTER` branch. It logs through `self._log(...)`. Entering the mode
  belongs there, behind `config.mode is DetectorMode.ACT`.
- The ring is not reset by the detector after a `would-enter`. A further cycle logs `would-enter` again, with a higher
  count. Act mode should decide whether entering the mode clears the ring.
- `blocked_hours` is validated and delivered, but no code reads it yet. Act mode's TTL reads it.
- Release note 024 and the unblock command are still open.

## Part B (6.3 + 6.4): handoff, no code written

The part B agent (brief `untracked/scratch/brief-501-phase6b.md`, worktree `worktree-501-phase6b-act`, base `b2a25304d`)
passed the 150k soft budget on reading alone and stopped before any code. It wrote down the design it had pinned, so the
next agent can start at the red tests and does not need to re-read anything. **6.3 and 6.4 are not ticked.**

### Facts established (do not re-read)

- **A Stop allow cannot carry the one-time line.** `HookResult._format_stop_response` (core/hook_result.py ~743) sends
  ALLOW context as `additionalContext`, which Claude Code treats as "continue the conversation". That prolongs the very
  loop being stopped, and the context is dropped on a `stop_hook_active` re-entry. **Deliver the line as a registry
  notice.** `core/session_mode_statement.pending_mode_statement` is the single consumer, and it states pending notices
  on every prompt that reaches `focus_mode_trigger` (ticks, the supervisor's line and the human's prompt alike).
- The registry has no public way to queue a notice. `_notices` is filled only by `_set`, so add one (below).
- **The human-prompt exit is already pinned for GOAL_BLOCKED**:
  `tests/unit/handlers/user_prompt_submit/test_failsafe_cron_blockage_suppressor.py::TestHandle::test_real_prompt_clears_goal_blocked_too`.
  6.4 only needs a test that the EXIT transition is logged with its evidence. Use the registry built by
  `pin_session_modes`, whose `transition_log.recent(...)` shows it.
- The IPC dispatch is `server.py:2709` (`elif action in SessionModeIPC.ACTIONS`), so adding an action to
  `constants/modes.SessionModeIPC.ACTIONS` is enough to route it.
  - `tests/unit/daemon/test_session_mode_ipc.py::TestActions::test_the_action_names` pins the exact set; update it.
  - The CLI argparse is `daemon/cli.py:~11011`, `choices=["get", "focus"]`. The request builder is
    `_session_mode_request` (~2212), and `cmd_session_mode` is at ~2346.
  - `_send_session_mode_ipc` already prints `ERROR: <error>` and the command returns 1 on an `{"error": ...}`
    answer. That gives the refusal its exit code with no new CLI code.
- `Assessment.evidence` already includes `mode=<mode>`. `CycleRing._reset` clears the fingerprint as well as the
  cycles.
- Test seams already present in the handler are `_fingerprint_repo`, `_append_transition` and `_clock`. The tests'
  `handler` fixture sets `_fingerprint_repo = lambda: "fp-stable"` and a `_Recorder`.
- `tests/support/autonomy.py`:
  - `pin_session_modes(monkeypatch, tmp_path, *entries)` returns a real registry with a transition log;
  - `awaiting_human_entry(sid)` returns a declared BLOCKED entry.

### Pinned design

1. **`core/goal_loop.py`**
   - Add `DetectorMode.ACT = "act"`.
   - Add a `GoalLoopConfig.blocked_seconds` property (`blocked_hours * 3600`).
   - Add `CycleRing.restart_count()`. It empties the cycles and the pending stop but KEEPS the fingerprint, so a later
     repo change is still seen. It logs nothing: the would-enter or enter line is the record.
   - Update the existing handler test `test_validate_options_is_the_core_option_check`: `mode: act` is now valid, so
     use `mode: "halt"`.
2. **`utils/session_modes.py`**: add `goal_loop_blocked_entry(session_id, *, entered_at, ttl_seconds)`, with
   `BLOCKED`, `GOAL_LOOP`, `ModeSource.DETECTOR` and `Lifetime.SESSION`, next to `declared_blocked_entry`.
3. **`core/session_mode_registry.py`**
   - Add `NoticeKind.GOAL_LOOP_ENTERED`, and `ModeNotice.goal_cleared: bool | None = None`.
   - `text()` for that kind states the following, mirroring the wording of `FocusChange.line` for a failed clear:
     - the session is goal-blocked by the detector;
     - the goal is being cleared (the supervisor types `/goal clear`; without it a human must type it), OR the clear
       could not be signalled, so a human must type `/goal clear`;
     - it ends after N h, at the next message the human types, on a repository change, or with
       `hooks-daemon session-mode unblock`.
   - Add a public `queue_notice(notice)` (under the lock, appended to `_notices[entry.session_id]`).
   - Add one sentence to the `session_mode_statement` docstring naming the new notice source.
4. **New `core/goal_loop_block.py`** (write `tests/unit/core/test_goal_loop_block.py` FIRST; tdd_enforcement):
   - `enter_goal_loop(registry, session_id, *, ttl_seconds, evidence, clear_goal) -> bool`:
     - `registry.enter(goal_loop_blocked_entry(...), evidence=evidence)`;
     - `cleared = clear_goal(session_id)`, with a WARNING when it is False;
     - `registry.queue_notice(ModeNotice(GOAL_LOOP_ENTERED, entry, goal_cleared=cleared))`;
     - return `cleared`.
   - `class DeclaredBlockRefusedError(ValueError)` is **the named error**.
   - `unblock_goal_loop(registry, session_id, *, evidence) -> UnblockChange(outcome, declared_remains)`. Its cases:
     - a live GOAL_BLOCKED: `registry.exit(..., GOAL_BLOCKED, evidence=evidence)`, giving outcome `unblocked`;
       `declared_remains` is True if AWAITING_HUMAN is also live, and the line says so;
     - only AWAITING_HUMAN live: log a WARNING and **raise `DeclaredBlockRefusedError`**. The message says that the
       awaiting-human mode ends only on a genuine prompt from the human in this session (Plan 00501 Phase 2);
     - neither: `not-blocked`.
     - `UnblockChange.line()` gives one sentence per outcome.
   - Tests: entry, notice text (cleared and failed), the timer exit (a registry with an injected clock past
     `expires_at` shows `policy().entries == ()`, and the transition log shows EXPIRE with "its expiry time passed"),
     unblock success (logged EXIT with the cause), **the refusal for a declared entry** (and the entry is still live
     afterwards), the both-live case, and not-blocked.
5. **IPC and CLI**
   - Add `SessionModeIPC.ACTION_EXIT_BLOCKED = "exit_blocked"` to `ACTIONS`.
   - In `session_mode_ipc._answer`, call `unblock_goal_loop(registry, sid, evidence="cause=explicit-clear (the session-mode CLI or /mode skill)")` and return `{outcome, line}`. In `handle_session_mode_action`, catch
     `DeclaredBlockRefusedError`, which gives `{"error": str(error)}`.
   - CLI: `choices=["get", "focus", "unblock"]`, and update the help text. In `_session_mode_request`, have
     `verb == "unblock"` send the `exit_blocked` request BEFORE the `if not words` check. `cmd_session_mode` prints
     the line.
   - Tests:
     - IPC: the action set; unblock ends goal-blocked with explicit-clear evidence; **unblock with only a declared
       entry returns an error and the entry stays**.
     - CLI: the unblock request shape; an error answer gives exit code 1.
6. **Handler `handlers/stop/goal_loop_detector.py`**
   - New seams: `_registry: Callable[[], SessionModeRegistry]` (default `get_data_layer().session_modes`) and
     `_clear_goal: Callable[[str], bool]` (default: a deferred import of `daemon.session_mode_ipc.clear_goal_signal`,
     to avoid the import cycle).
   - Add `_SessionState.blocked_fingerprint: str | None`. It is in memory only, so a daemon restart loses the
     repo-change exit for an entry already live; the timer and human exits still apply. State this in the docstring.
   - `handle()`, after the feed and the reset logging:
     - Fingerprint when `new_cycles > 0 or state.blocked_fingerprint is not None`. Compute it once, and on
       `FingerprintError` give a WARNING and allow.
     - If `blocked_fingerprint` is set:
       - if the registry no longer holds a live GOAL_BLOCKED, drop it;
       - else if the fingerprint differs, `registry.exit(sid, GOAL_BLOCKED, evidence=f"cause=repo-change fingerprint={old}->{new}")` and drop it.
       - `RuntimeError` and `OSError` give a `log_and_continue` WARNING.
     - When `new_cycles == 0`, return.
     - WOULD_ENTER:
       - in ACT, `enter_goal_loop(... ttl_seconds=config.blocked_seconds, evidence=assessment.evidence(...))`, then
         set `blocked_fingerprint`; `RuntimeError` and `OSError` give a WARNING and the Stop is still allowed;
       - in OBSERVE, log `WOULD_ENTER` as now;
       - then, in both, `state.ring.restart_count()`, so the loop is logged once, not on every further Stop.
     - NEAR_MISS is unchanged. Never `continue:false`, and always allow.
     - A re-entry while the entry is still live simply re-enters, which renews the TTL and re-signals the clear.
   - Update the module docstring: act mode, the exits, and the no-ccy backstop. The backstop is Claude Code's built-in
     cap of 8 consecutive stop-hook continuations (each tool call resets it; `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` raises
     it). After it, Claude Code pauses the goal until the next message, a tick included. A loop that makes tool calls
     between stops never reaches the cap.
   - Keep `get_claude_md()` as None. Act is opt-in, and turning guidance on would remove the guidance-coverage
     exemption and change the generated CLAUDE.md block. Record this as a deliberate choice.
   - Handler tests:
     - act enters (via a real `pin_session_modes` registry), clears once, and queues one notice;
     - observe logs WOULD_ENTER once and not again on a fourth cycle;
     - act then a repo change exits with the cause logged;
     - act with an entry already ended by a human drops the fingerprint;
     - an enter failure is a WARNING and the Stop is allowed.
7. **Docs and wiring**
   - Restore the `mode` row (`observe` | `act`) in the `docs/guides/HANDLER_REFERENCE.md` options table, and document
     the backstop there.
   - Add `("goal_loop_detector", "mode"): "act"` to `_VALID_NON_DEFAULTS` in `test_registry_option_injection.py`.
   - Mention `act` in the commented options of `.claude/hooks-daemon.yaml.example`.
   - Write the release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/024-goal-loop-detector.md`. It covers the
     detector shipping in observe mode only, `act` as opt-in, `session-mode unblock` and its refusal of awaiting-human,
     and the backstop.
   - Tick 6.3 and 6.4 in PLAN.md.
8. **QA**: `FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range b2a25304d..HEAD --allow-unmapped > untracked/scratch/qa-501p6b.txt 2>&1`,
   then grep it for `^QA:` and `^❌`.

### Advice to the coordinator

Split the rest across two agents and give each only this section:

- **B1**: items 1 to 4 (core plus the registry notice), with their tests.
- **B2**: items 5 to 8 (IPC, CLI, handler, docs, note, QA).

The injected guidance is about 60k tokens on its own, so each agent has about 90k tokens of working room.
