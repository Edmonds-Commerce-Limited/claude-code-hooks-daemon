# Plan 00523 follow-ups report

Built test-first in `tests/unit/supervise/test_rate_limit_dialog.py` (15 new tests failed first); the whole `tests/unit/supervise` directory passes (1967), ruff clean. No full gate, no hooks-screen build.

Done, all in `.claude/ccy/claude-supervise.py`:

- **F1**: `_sweep_rate_limit_states` keeps a state whose occurrence is open and which holds no resume (taken over, key-capped), as the load does.
- **F2**: `_apply_worker_outcome` takes an `on_held` callback; the host passes `_rate_limit_host_held`, which takes back a held Enter, clear or `continue` the same way a vetoed one is. `_rate_limit_host_veto` now uses it too.
- **F3**: a vetoed resume send records `resume_vetoed_at`; output within 5 s of it is the veto's own redraw and does not open the post-reset re-check, so an empty box is retried instead of abandoned at the deadline.
- **F4**: the Review item was under-specified. Taking an Enter back means it never landed, so one re-answer is right. I added `_RATE_LIMIT_TAKEBACK_CAP = 2` taken-back Enters per window; after that the dialog is left alone.
- **Task 2.4**: `rate_limit_armed_status(dry_run=)` returns an `ARMED`, `dry-run` or `OFF` line (key `CCY_RATE_LIMIT_DIALOG`). It is in the startup banner (`render_startup_banner(extra_lines=)`) and is the second decision-log line (after `supervisor active`). Corrected by the independent review: it can also read `INERT` when no hooks-screen binary resolves.
- Docs in `CLAUDE/development/CcySupervisor.md`; release note `090-rate-limit-dialog-follow-ups.md`.

Hot reload (corrected by the independent review): only the sweep rule reloads by itself. The host writes `enter_takebacks` and `resume_vetoed_at`, so F2, F3 and F4 (like the banner line) need a ccy relaunch; under an older host F3 and F4 are inert and fail safe. I did not restart anything.

Blocked or not built:

- **Task 3.1 and Phase 1 live capture**: need a real rate-limit hit.
- **Phase 2b (2b.1-2b.3)**: not built. The `.usage-paused` record (daemon writer, supervisor parser copy, pinned by `test_usage_pause.py`) has no field to tell a hard limit from a ceiling pause, so 2b.2 has nothing to key on without a schema change in both halves. Plan 00630 Q16 may also retire the ceiling pause. It needs an owner design ruling. 2b.3 (back-off) has no retry loop to hang on until 2b.1 exists.
- F4's exact intent should be confirmed by the owner (the cap of 2 is my choice).
