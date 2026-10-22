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
