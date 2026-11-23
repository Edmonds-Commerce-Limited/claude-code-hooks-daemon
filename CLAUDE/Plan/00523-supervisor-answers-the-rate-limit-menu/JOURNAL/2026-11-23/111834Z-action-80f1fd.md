## 11:18 · action · —

Closed the two open risks from handoff 5, test-first, then did the paperwork. The plan stays In Progress, pending independent review and the full gate.

Risk 1: the model restore could be typed onto the pre-filled box. The host's `input_line_empty` counts typed keys only, so Claude Code's pre-filled `continue` is invisible to it. The new `_rate_limit_prefill_blocks` folds into `can_inject` and into the usage-pause `/compact`. It blocks every family while a resume is pending (phase answered or cleared, even with no screen). In any later phase it blocks only while the screen still shows the pre-fill, which covers the abandoned and dry-run cases. The restore therefore goes after the continue. Commit `d4e5b2f02`.

Risk 2: an idle redraw after the reset killed the resume. Output after the reset in phase answered now opens a bounded re-check of 600 s, stored once as `resume_recheck_until`. Once the screen settles, a box still showing the pre-fill proves nothing was submitted, so the resume clears it and continues. An empty box is ambiguous, because the human may have continued, so the supervisor waits and abandons the window at the deadline. The resume still runs once per window and still fails closed. The old abandon-at-once test was rewritten deliberately. Commit `1dc68225e`.

Docs are in `CcySupervisor.md`, and `ccy.env` lists `CCY_RATE_LIMIT_DIALOG` (`76cab97bf`). The PLAN ticks, README row and release note 025 are in `435d83b77`.

Checks were light only: the rate-limit, screen-focus, idle-compact, policy-worker, usage-pause, session-modes, dry-run, model-restore and focus-hold test files (538 passed), the ccy.env and integrity tests (193 passed), and ruff, black and mypy on the touched files. The full gate has not been run.

Still open:

- Phase 1, the live capture: the fixtures are reconstructed.
- Phase 2b.
- The fallback path gets no screen dump.
- Whether Claude Code's own auto-continue can duplicate ours is unknown.
- Review, the full gate and the merge.
