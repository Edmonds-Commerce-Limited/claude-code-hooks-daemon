# r3.71 review fixes: session modes (D1, D2, D5, N1)

Branch `worktree-r371-session-modes`, base `df6c44a3b`. Source review:
`untracked/agent-reports/auto/261023-164950-code-reviewer-a003b87b9593b4488.md`.

## D1: one unreadable session-modes file disables the registry (medium): REAL

- **Reproduced.** `probe_registry_load_poison.py` (run with this worktree's venv): load 1 raised
  `IsADirectoryError`, aaa's file had already been rewritten, load 2 raised again, and aaa's
  CLEARED_BY_RESTART notice was lost.
- **Tests (written RED first):**
  - `tests/unit/core/test_session_mode_registry.py::TestOneBadFileAffectsOnlyItsSession::test_an_unreadable_file_is_logged_and_skipped_and_the_others_load`
  - `...::test_a_failed_rewrite_keeps_the_loaded_state_and_logs_an_error`
  - `tests/unit/core/test_data_layer.py::TestSessionModesProperty::test_an_unreadable_session_file_does_not_disable_the_registry`
  - `...::test_a_failed_legacy_import_keeps_the_loaded_registry_and_its_notices`
- **Fix:**
  - `src/claude_code_hooks_daemon/core/session_mode_registry.py:395-418` (`_load_file`): an `OSError`
    while reading one file is logged at ERROR through `log_and_continue` (not silent) and only that file
    is skipped. The file is left in place, because a read failure says nothing about its content, so it
    is not quarantined as corrupt.
  - `session_mode_registry.py:~441-452` (`_apply_restart_rules`): a failed rewrite is logged at ERROR
    and the loaded state is still adopted. The file is then a superset of memory, and the session's next
    write replaces it.
  - `src/claude_code_hooks_daemon/core/data_layer.py:~139-158`: the registry is cached as soon as
    `load()` returns. A failing `import_legacy_blockage_marker` is logged at ERROR rather than raised, so
    the registry is never rebuilt and its notices are kept.
  - `load()` now raises `OSError` only when the state directory itself cannot be listed.

## D2: an attributed clear can be attributed again after a restart (medium): REAL

- **Reproduced.** `probe_reattribution.py`: the first pass gave "supervisor"; after eviction the key
  was no longer seen, and the re-read gave "human record=none". I also confirmed the handler path: the
  detector skipped a clear only if its key was in `TransitionLog.recent(500)`.
- **Tests (RED first):**
  - `tests/unit/handlers/stop/test_goal_loop_detector.py::TestGoalClearAttribution::test_a_restart_after_the_log_record_is_evicted_does_not_attribute_again`
    (a fresh detector, with the log returning nothing, must not log a second clear or enter manual goals)
  - `...::test_a_failed_mark_leaves_the_clear_unattributed_and_the_stop_allowed`
  - `...::test_default_attributed_clears_path_is_in_the_daemon_untracked_dir`
  - `test_no_clear_reads_neither_the_log_nor_the_record_directory` now also asserts the store is not read
  - `tests/unit/core/test_goal_clear_attribution.py::TestAttributedClears` (17 cases: persistence across
    instances, the high-water mark, keys sharing a timestamp, per-session marks, the bound, rejecting
    a bound below 1, no temp file left behind, corrupt-store quarantine (8 shapes), and an unreadable
    store raising `OSError`)
- **Fix:**
  - `src/claude_code_hooks_daemon/core/goal_clear_attribution.py:295-420`: new `AttributedClears`, a
    durable store kept separate from the log, in `<daemon untracked>/goal-clear-attributed.json`. For
    each session it keeps a high-water mark: the latest attributed clear's time, plus every key at
    exactly that time. Transcript clears are in time order, so anything at or before the mark is
    already done.
  - It is bounded to `MAX_ATTRIBUTED_SESSIONS = 1024` sessions; the session with the oldest mark is
    dropped first.
  - Writes are atomic (temp file, then replace) and guarded by a lock. A malformed store is renamed to
    `.corrupt`, logged at WARNING, and raises `AttributedClearsError`.
  - `src/claude_code_hooks_daemon/handlers/stop/goal_loop_detector.py:345-350`: a clear is skipped if the
    log's keys **or** the store cover it. The store is marked **before** `attribute_clear`. If anything
    fails after the mark, the clear is left unattributed and goals stay as they were, which is the
    module's documented safe direction. It is never attributed twice. The existing log-key check is kept
    for clears attributed before this store existed.
- **Why not a file per session in the sidecar dir:** the supervisor reaps that directory by suffix on a
  30-minute TTL, and a file it does not reap would leak one file per session. A single bounded file
  owned by the daemon avoids both problems.
- **Why not "skip clears before `loaded_at`":** that does not cover a session dropping out of the
  detector's 64-session list within one daemon process. The checkpoint is lost there too and the tail
  is re-read.
- **Probe note:** `probe_reattribution.py` still prints "human" because it calls `attribute_clear`
  directly. That function is unchanged; the guard against attributing twice is in the caller and the
  store.

## D5: the manual-goals message claims more than it does (low): REAL, the message was corrected

- **Decision, from the plan:** Plan 00501 Task 8.3 scopes the mode as "only `.goal-intent` writing is
  suppressed". MANUAL-GOALS.md defines "suppress goal injection" as "the daemon writes no goal-intent
  signal".
  - The commit that added the message (`92421a271`) also added the `clear_automated_goal_signal`
    docstring, which states that the goal-loop detector's loop-breaking clear is **not** gated.
  - Gating it would let a looping manual-goals session loop with no daemon-side brake, which defeats
    Phase 6.
  - So the behaviour is the intended one, and the message was the error. I corrected the message
    rather than gate the detector. That departs from the dispatch's stated preference, and this
    evidence is why.
- **Test (RED first):** `tests/unit/core/test_manual_goals.py::TestLines::test_the_entry_line_does_not_promise_the_loop_breaker_is_gated`
- **Fix:** `src/claude_code_hooks_daemon/core/manual_goals.py:83-85` now reads "no plan-driven clear
  removes a goal (the goal-loop detector can still clear a goal to break a loop)".
  - I made the same wording change in one test-class docstring,
    `tests/unit/handlers/post_tool_use/test_goal_injection_manual_goals.py:131`.

## N1: a design question only, not changed

When the supervisor is absent, the notices in `goal_loop_block.py:132-134` and `focus_mode.py:131-133`
tell the human to type `/goal clear`. That clear has no supervisor record, so it is attributed to the
human and the session enters manual goals, which lasts until `goals on`.

So following the daemon's own instruction switches automated goals off for the session. The owner
should decide whether that is intended. Options:

- (a) Accept it, and have the notice say so.
- (b) Have the daemon write its own "expected clear" record when it issues that instruction.
- (c) Word the notice so that it suggests `goals on` afterwards.

## Verification

- Targeted tests: 273 passed across the 6 touched test modules.
- QA: see "Final QA" below.

## Final QA

`llm_qa.py changed --range df6c44a3b..HEAD --allow-unmapped`, run on a clean tree at the fix commit
`a58301156`, gave `QA: 41/41 PASSED` with no `❌` lines. The full output is in
`untracked/scratch/qa-r371-sm.txt`.

The head sha is the commit that adds this report. Its parent, `a58301156`, holds all the code changes.
