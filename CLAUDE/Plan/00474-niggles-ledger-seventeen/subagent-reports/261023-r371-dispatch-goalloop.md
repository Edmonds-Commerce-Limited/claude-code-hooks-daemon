# Release v3.71.0 review fixes: D3 (bounded dispatch), D4 (goal loop), N2 (noted)

Branch `worktree-r371-dispatch-goalloop`, base `df6c44a3b` (release/3.71.0).
Source findings: `untracked/agent-reports/auto/261023-164950-code-reviewer-a003b87b9593b4488.md`.

## D3: exempt stragglers used up the ordinary straggler cap

- **Real?** Yes. `probe_exempt_straggler_counts.py` against the base tree:
  after one timed-out `capacity_exempt` call with `max_stragglers=1`,
  `straggler_health()` was `count=1, at_capacity=True` and the next ordinary
  call returned `DispatchSaturated`.
- **Test (RED then GREEN):**
  `tests/unit/core/test_bounded_dispatch.py:768`
  `TestBoundedDispatcherCapacityExemptCalls::test_an_exempt_straggler_does_not_use_up_the_ordinary_straggler_cap`
  (failed on base with `assert True is False` on `health.at_capacity`).
- **Fix:** `src/claude_code_hooks_daemon/core/bounded_dispatch.py:366-380`.
  In `run()`'s timeout branch the `_stragglers` record is now made only for
  non-exempt calls (moved inside the existing `if not capacity_exempt:`).
  An exempt straggler keeps its exempt slot until it really finishes, which
  is its bound (unchanged, still covered by
  `test_an_exempt_straggler_keeps_its_exempt_slot_until_it_finishes`). This
  matches the documented intent ("which no straggler cap counts", and the
  `run()` docstring "Run past both the in-flight and the straggler cap").
  The `straggler_health()` docstring (`:495-500`) now says it counts ordinary
  stragglers only. A late exempt completion is still logged by
  `_log_late_completion`.
- **After:** the probe prints `count=0, at_capacity=False` and
  `ordinary call result: ok`.

## D4: `read_new_lines` could return a mid-line checkpoint

- **Real?** Yes. `probe_midline_checkpoint.py` on base: first read returned
  offset 57 with the byte before it `b'y'` (mid-line); the second read
  returned the fragment `'yyyy...y"}'` as a line.
- **Tests (RED then GREEN):** `tests/unit/core/test_goal_loop.py`
  - `:176` `TestReadNewLines::test_a_tail_inside_one_unfinished_line_never_checkpoints_mid_line`
    (first sight: checkpoint is offset 0; the later read never yields the
    trailing fragment as a line)
  - `:192` `TestReadNewLines::test_a_backlog_tail_inside_one_line_keeps_the_previous_checkpoint`
    (checkpointed backlog case: the returned checkpoint equals the previous one)
- **Fix:** `src/claude_code_hooks_daemon/core/goal_loop.py:325-330`. When
  the whole tail lies inside one unfinished line, return the last known line
  boundary: the incoming checkpoint's offset, or 0 (file start) on first
  sight. The next read is again past `tail_bytes`, so it is still bounded and
  takes the tail path with mid-line handling. The only consumer
  (`handlers/stop/goal_loop_detector.py:213`) treats the checkpoint as opaque.
- **After:** the probe's first read gives offset 0 and the second read
  returns only whole lines.

## N2: pool sizes live in the `Timeout` class (suggestion, not changed)

`constants/timeout.py` holds `DISPATCH_MAX_INFLIGHT` and
`DISPATCH_EXEMPT_MAX_INFLIGHT`, which are counts, not durations. Moving
them to a dispatch/limits constants class would fix the naming. Not changed,
as instructed. Note that `tests/unit/core/test_bounded_dispatch.py:578`
asserts on `Timeout.DISPATCH_EXEMPT_MAX_INFLIGHT`, so a move would touch it.

## QA

Fix commit `a8a8adc01`, clean tree:
`FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range df6c44a3b..HEAD --allow-unmapped`
gave exit 0 and `QA: 41/41 PASSED`, with no `❌` lines
(`untracked/scratch/qa-r371-dg.txt`). Before that, the
dispatch, chain and controller unit tests passed, and so did the goal-loop and
goal-loop-block tests. This report is committed on top of `a8a8adc01` and
changes no code.
