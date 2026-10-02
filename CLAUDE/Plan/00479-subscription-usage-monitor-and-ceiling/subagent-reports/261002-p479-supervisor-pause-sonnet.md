# Plan 00479 Task 4.5: pause record and supervisor behaviour

## Findings (all read, with paths)

- Daemon writer of the compaction record: `src/claude_code_hooks_daemon/handlers/pre_compact/compaction_signal.py` (`_write_signal`, atomic via `unique_temp_path`, `<stem>.compacting` in `ProjectContext.daemon_untracked_dir()/context-sidecar`).
- Supervisor reader: `.claude/ccy/claude-supervise.py` `load_compaction_signal`, `load_compaction_origin` (stdlib-only script, parses the JSON itself, cannot import the package). Own-session filter: `_session_in_scope`.
- Closest shared-module convention: `src/claude_code_hooks_daemon/utils/operator_signal.py` (daemon-side constants, supervisor keeps copies pinned by a lockstep test, `tests/unit/supervise/test_operator_signal.py`).
- Injection decisions: `decide_once` (supervisor) calls `CompactStateMachine.evaluate` (`/compact` and `continue`), then the goal, goal-clear, standing-auth, model, operator and session-actions families. Idle notion: `can_inject = facts.idle and facts.input_line_empty` plus `facts.work_idle` (from `_is_idle`, `_is_work_idle`).

## Relation to cron_pause

`src/claude_code_hooks_daemon/utils/cron_pause.py` is deliberately NOT reused or extended. It is CLI-set, a fixed 24 h TTL, one file for all sessions, and read inside the daemon by the cron enforcers. The usage record must be a per-session file the supervisor can glob like every other signal, and it ends at the window reset, not after a fixed TTL. Shared discipline, copied: own session only, future-dated refused, expired refused (`resume_at` + `PAUSE_GRACE_SECONDS`), reads fail open (unreadable is no pause, logged), writes and clears raise. `cron_pause.py` is unchanged.

## Interface

`src/claude_code_hooks_daemon/utils/usage_pause.py`: frozen `UsagePause(session_id, paused_at, resume_at, window, used_percentage, ceiling, reason)` with `is_live(session_id=, now=)` and `expires_at`; `pause_path(daemon_untracked_dir, session_id)`; `write_usage_pause(daemon_untracked_dir, pause) -> Path` (validates, raises `ValueError`/`OSError`); `read_usage_pause(daemon_untracked_dir, session_id, *, now) -> UsagePause | None`; `clear_usage_pause(daemon_untracked_dir, session_id) -> bool`. Constants: `SIGNAL_SUFFIX = ".usage-paused"`, `WINDOW_FIVE_HOUR`, `WINDOW_SEVEN_DAY`, `WINDOWS`, `PAUSE_GRACE_SECONDS = 3600`.

Beyond the six requested fields the record carries `session_id` (needed for the own-session filter; the filename stem is sanitised).

File: `<daemon_untracked_dir>/context-sidecar/<session>.usage-paused` (self-install: `untracked/context-sidecar/`).

## Supervisor

`load_usage_pause` and `_usage_pause_outcome` in `.claude/ccy/claude-supervise.py`; the hook point is in `decide_once`, right after `machine.import_state`, ahead of `machine.evaluate`. Documented in `CLAUDE/development/CcySupervisor.md`, section "The usage pause: one compact, then silence".

## Design decisions to review

- The latch (`pause_compacted_for`, keyed by `paused_at`) is set at decision time and round-trips through `export_state`/`import_state`. The running PTY host predates the key and ignores it, so a worker reload or crash MID-PAUSE loses the latch and types one more compact. Documented as a known limit.
- A pasted-but-unsubmitted pause compact gets no bare-Enter follow-up (the machinery that does that is bypassed). Documented.
- The compaction signal the pause compact produces is not consumed (the host only consumes on a payload); it expires by TTL, so a lift inside that window may type one `continue`, which is normal behaviour resuming.
- `.usage-paused` is deliberately NOT in `reap_stale_sidecars`: that reaps by mtime after 30 min, which would lift a multi-hour pause. Expiry is by the record's own `resume_at` + grace.
