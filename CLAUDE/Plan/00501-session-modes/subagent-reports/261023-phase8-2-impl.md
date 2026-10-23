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

## Part 2

The Part 1 "Left" list is done. Task 8.2 is ticked.

### What changed

1. **Supervisor** (`.claude/ccy/claude-supervise.py`, commit `62aa79036`):
   - Added `_GOAL_CLEAR_RECORD_SUFFIX` and `write_goal_clear_record(directory, *, trigger_path, now)`. The write is
     atomic: a pid-qualified temp file, then `replace`. If the replace fails, the temp file is removed and the error is
     raised again.
   - `decide_once` writes the record in the armed, non-dry-run branch, before it sets `payload = _GOAL_CLEAR_COMMAND`.
   - If the write raises `OSError`, no clear is typed. The trigger is left in place for the next tick, and
     `noop_reason_log` reads `noop: goal clear NOT typed: attribution record could not be written: <error>`.
   - `reap_stale_sidecars` also reaps `*.goal-clear-injected`.
   - Tests are in `tests/unit/supervise/test_goal_clear_record.py`. They check that the suffix matches the daemon's,
     that the record is not picked up by the `*.goal-clear` glob, and that the daemon's `read_clear_record` accepts
     what the supervisor writes. They also cover the record being written before typing, no record on a dry run, no
     clear when the write fails (a directory sits at the record path), and reaping.
2. **Registry line channel** (commit `28497cdb0`):
   - Added `SessionModeRegistry.queue_line` and `take_lines`, a pop-once queue separate from `_notices`. A blank line
     raises `ValueError`.
   - `pending_mode_statement` adds these lines to its single `SESSION MODE:` line, after the notices. It is still the
     only consumer.
3. **Stop wiring** (`handlers/stop/goal_loop_detector.py`, commit `b3ea769ba`):
   - Added `_attribute_clears`, which runs straight after `read_new_lines`. It skips clears whose keys the transition
     log already holds, then logs each new verdict as a `goal-clear` transition. When the verdict carries a line, the
     line is queued with `registry.queue_line`.
   - Added two seams, `_recent_transitions` and `_clear_record_dir`. The defaults are the data layer's log and
     `ProjectContext.daemon_untracked_dir() / SIGNAL_SUBDIR`.
   - Any of `OSError`, `RuntimeError`, `GoalClearAttributionError` or `TransitionLogError` is a `log_and_continue`
     WARNING, and the Stop is still allowed. The module docstring is updated.
   - New tests are in `TestGoalClearAttribution` in `tests/unit/handlers/stop/test_goal_loop_detector.py`. They run
     the real `handle()` with a real registry and transition log, and cover supervisor, human, supervisor-assumed
     (with the queued line), restart dedupe, only-new-clears, failure, a clear with no timestamp, the no-clear fast
     path, and the defaults.
4. **Release note**: `CLAUDE/UPGRADES/UNRELEASED/release-notes/025-goal-clear-attribution.md` (commit `b3ea769ba`).
   It records the three known gaps above.
5. **QA fixes** (commit `41fc4a8ae`):
   - The first QA run flagged two `error_hiding` findings in the Part 1 module `core/goal_clear_attribution.py`.
     - `read_clear_record` now checks `path.exists()` instead of catching `FileNotFoundError`. If the record vanishes
       between the check and the read, the clear is treated as unreadable (supervisor-assumed), which is safe.
     - A transcript line that is not JSON is passed through `log_and_continue` at DEBUG.
   - It also flagged 7 pyright errors in the new supervisor test. The `_decide` return type is now `Any`, with a
     comment: the supervisor is loaded from a script path, so its types cannot be imported.
   - `run_autofix.sh` changed nothing.

### Final QA

`llm_qa.py changed --range 2c3ed0301..HEAD --allow-unmapped` on the clean tree at `41fc4a8ae`: `QA: 41/41 PASSED`.
The full output is in `untracked/scratch/qa-501p8.txt`.

### Head

The head is the commit that adds this section and the PLAN.md tick, on top of `41fc4a8ae`. The branch is pushed. It
is not merged, and the daemon was not restarted. The running supervisor picks up the new code when its worker
hot-reloads; see `CLAUDE/development/CcySupervisor.md`.
