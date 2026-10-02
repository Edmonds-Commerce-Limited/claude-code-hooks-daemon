# Plan 00479 Tasks 1.2, 2.1, 2.2: usage snapshot and status segment

## Snapshot (Task 2.1)

- Module `src/claude_code_hooks_daemon/core/usage_snapshot.py`: `UsageWindow(used_percentage, resets_at, observed_at)`, `UsageSnapshot(five_hour, seven_day)`, `UsageTracker`.
- Memory: `get_data_layer().usage` (a `UsageTracker`), updated by `DaemonController.process_event` on each STATUS_LINE event, beside `SessionState`.
- File: `{daemon_untracked_dir}/usage-snapshot.json` (`usage_state_file()`; `resolve_usage_state_file()` for the running project). Atomic (`unique_temp_path` + `replace`), written on change or every 60 s, OSError logged at WARNING and swallowed.
- Accessor: `core.data_layer.latest_usage(*, now: float | None = None) -> UsageSnapshot | None`. Memory first, file fallback while memory is empty. Windows with `resets_at <= now` are dropped; None when none is live.
- Ceiling-ready: `UsageSnapshot.highest_used_percentage()`, `UsageWindow.observed_at` (for a staleness check), `UsageWindow.seconds_until_reset(now)`.
- Event without `rate_limits`, or with malformed windows, changes nothing. One window present updates only that window. Percent outside 0-100, bool, NaN, non-positive `resets_at` are rejected.
- Not established: whether subagent threads carry `rate_limits`. Fixture `agent_thread.json` assumes they do; the code reads any payload that has it.

## Segment (Task 2.2)

- `handlers/status_line/usage_indicator.py`, `HandlerID.USAGE_INDICATOR`, `Priority.USAGE_INDICATOR = 16`, default enabled.
- Options (defaults): `warn_pct` 60, `high_pct` 80, `critical_pct` 90, `seven_day_countdown_pct` 80.
- 5h countdown always; 7d countdown from 80%. Colours are model_context's SGR codes (green, yellow, orange 208, bold bright red). Percentages floor.
- Examples: `5h 13% (3h 0m) · 7d 3%`; `5h 67% (3h 0m) · 7d 81% (6d 22h)`; `7d 42%`; nothing with no data.
- `get_claude_md()` is None; added to `_EXEMPT_FROM_GUIDANCE` beside every other status renderer (all 16 siblings are in that list).
- Registered in both yaml files, `status_line/__init__.py`, status-line count tests; `.claude/HOOKS-DAEMON.md` regenerated with `generate-docs`; release note 211; config-changes entry in v3.68.0.yaml; `CLAUDE/Architecture/StatusLine.md` updated.
