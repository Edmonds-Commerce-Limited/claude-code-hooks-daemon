# Plan 00501 Task 8.2: goal-clear attribution, implementation report

Branch `worktree-501-phase8-attribution`, base `2c3ed0301`, head `cf46eedaf` (pushed). Stopped at a clean commit:
the agent passed its 150k soft context budget. Task 8.2 is NOT ticked.

## Part 1

### Design chosen

- **Record path.** `<daemon untracked>/context-sidecar/<session_stem>.goal-clear-injected`. It is the same directory
  as the `.goal-intent` / `.goal-clear` signals: the daemon resolves it with `ProjectContext.daemon_untracked_dir() / SIGNAL_SUBDIR` and `session_stem()` from `utils/session_signal_paths.py`, and the supervisor resolves it as its own
  `sidecar_dir`. The suffix does not end in `.goal-clear`, so the supervisor's `*.goal-clear` trigger glob cannot pick
  it up (a test pins this). Payload: `{"session_id": <stem>, "ts": <epoch>, "command": "/goal clear"}`.
- **Freshness.** `FRESH_WINDOW_SECONDS = 120.0`. The supervisor writes the record in the same tick it types the
  command, and an idle Claude Code records a local command at once, so the real gap is under a second. Two minutes
  covers a slow PTY write or a loaded host. It is still short enough that a human clear typed later is not taken for
  an older supervisor clear that never landed. `CLOCK_TOLERANCE_SECONDS = 2.0` lets a record post-date the
  transcript's millisecond stamp slightly. Freshness is measured against the TRANSCRIPT record's timestamp, not the
  Stop's time, because the next Stop can come hours after an idle clear.
- **Attribution** (`core/goal_clear_attribution.py`):
  - A fresh record whose stem and command match is the supervisor's, and the record is consumed.
  - No record, a stale one, or one naming a different command or session is a human's.
  - An unreadable record (OSError, not JSON, wrong shape) is `supervisor-assumed`: WARNING, the record is removed,
    and `ClearVerdict.line()` gives the one line telling the human to type `/goal clear` again.
  - A blank session or a clear with no timestamp raises `GoalClearAttributionError`.
- **Output.** `ClearVerdict.transition()` returns a `ModeTransition` with `action=goal-clear`, `detail=<attribution>`,
  `evidence="clear=<transcript uuid> args=<token> record=<fresh|none|stale|mismatch|unreadable> …"`. Task 8.3
  consumes `action == goal-clear and detail == human`.
- **Restart dedupe.** On first sight after a daemon restart, the detector re-reads the last 2 MB of the transcript.
  Without a guard, an already-attributed clear (whose record is gone) would be logged again as a HUMAN clear.
  `attributed_keys(transitions)` returns the clear keys already in the log, and the Stop side must skip those.
- **Label (decision to review).** `ModeTransition` requires a `ModeLabel`, so I added `ModeLabel.MANUAL_GOALS = "manual-goals"` at the precedence position MANUAL-GOALS.md proposes (between awaiting-human and focus). Nothing
  enters it yet. No `_COLOURS`, exit hint or policy entry was added; that is Task 8.3's.

### Files changed (committed)

- `src/claude_code_hooks_daemon/core/goal_clear_attribution.py` (new)
- `tests/unit/core/test_goal_clear_attribution.py` (new, written first)
- `src/claude_code_hooks_daemon/core/session_mode_log.py` (`TransitionAction.GOAL_CLEAR`)
- `src/claude_code_hooks_daemon/utils/session_modes.py` (`ModeLabel.MANUAL_GOALS`)
- `tests/unit/utils/test_session_modes.py` (precedence order)

Targeted pytest on the new test file plus session_modes, session_mode_log, session_mode_registry and the
session-mode status-line indicator: all passed. On the new module, ruff, black and mypy are all clean. The
llm_qa `changed` run has NOT been done yet.

### Left

1. **Supervisor writer** (`.claude/ccy/claude-supervise.py`, TDD in a new `tests/unit/supervise/test_goal_clear_record.py`):
   - Add `_GOAL_CLEAR_RECORD_SUFFIX = ".goal-clear-injected"` and `write_goal_clear_record(directory, *, trigger_path, now)`. It derives the stem from the trigger name minus `.goal-clear`, and writes atomically with a
     pid temp file plus `replace`, following the pattern of `write_model_switch_signal` (around line 3586).
   - Call it in `decide_once`'s goal-RETRACTION branch (around line 8041), in the non-dry-run `else` before `payload = _GOAL_CLEAR_COMMAND`. The call goes there, at decision time in the worker, so a worker hot-reload deploys it.
   - On `OSError`, do NOT type the clear. Set `noop_reason_log` to say the attribution record was not written; an
     unrecorded clear would be misattributed to the human.
   - Add the new glob to `reap_stale_sidecars`.
2. **Registry line channel**:
   - Add `SessionModeRegistry.queue_line(session_id, text)` / `take_lines(session_id)`, a dict separate from
     `_notices`. `ModeNotice` needs an entry, and the unreadable case has none.
   - `core/session_mode_statement.pending_mode_statement` appends `take_lines()` to its parts.
   - Reason for this channel: Stop-result context is read as "continue" (see goal_loop_detector's docstring), so the
     line must reach the agent at its next prompt.
3. **Stop-side wiring** in `handlers/stop/goal_loop_detector.py`:
   - After `read_new_lines`, call `find_typed_clears(lines)`, skip the keys `attributed_keys(log.recent(MAX_TRANSITIONS, session_id=sid))` already holds, then `attribute_clear(...)` with directory `ProjectContext.daemon_untracked_dir() / SIGNAL_SUBDIR`.
   - Pass the result to `self._log(verdict.transition(sid))`. If `verdict.line()` is set, queue it via the registry.
   - Add seams for the record directory and the recent-transitions reader.
   - Catch `(OSError, RuntimeError, GoalClearAttributionError, TransitionLogError)` and handle it as a named WARNING,
     following the detector's never-break-a-Stop contract.
   - Update the docstring. Tests go in `tests/unit/handlers/stop/test_goal_loop_detector.py`.
4. Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/025-goal-clear-attribution.md` (follow 024's format).
5. Targeted QA: `FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range 2c3ed0301..HEAD --allow-unmapped > untracked/scratch/qa-501p8.txt 2>&1`, then grep `^QA:` / `^❌`. Then tick Task 8.2.
6. Known gaps to record:
   - A mid-turn human clear leaves only the `goal_status sentinel` snapshot, not the local_command pair, so it is not
     attributed. The supervisor types only when idle, so its own clears are always pairs.
   - The aliases are inferred from the mechanism, not observed (spike gap).
   - With the goal-loop detector disabled, nothing attributes.
