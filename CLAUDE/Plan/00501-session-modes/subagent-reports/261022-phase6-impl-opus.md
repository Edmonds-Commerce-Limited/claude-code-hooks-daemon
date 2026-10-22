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

QA_PLACEHOLDER

### What part B must know

- Add `DetectorMode.ACT`. Restore the `mode` row in HANDLER_REFERENCE.md and add the `_VALID_NON_DEFAULTS` entry (see
  the deviation above).
- `handle()` has one place to act: the `WOULD_ENTER` branch. It logs through `self._log(...)`. Entering the mode
  belongs there, behind `config.mode is DetectorMode.ACT`.
- The ring is not reset by the detector after a `would-enter`. A further cycle logs `would-enter` again, with a higher
  count. Act mode should decide whether entering the mode clears the ring.
- `blocked_hours` is validated and delivered, but no code reads it yet. Act mode's TTL reads it.
- Release note 024 and the unblock command are still open.
