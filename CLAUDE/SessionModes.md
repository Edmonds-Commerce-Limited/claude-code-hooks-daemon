# Session Modes

**Read first:** [CLAUDE/core/SessionModes.core.md](core/SessionModes.core.md) — the daemon's core
guidance for this subject, and the baseline everything below extends.

That file is DAEMON-owned: it is overwritten wholesale on every daemon upgrade,
so never edit it and never copy its content here. In this self-install checkout
edit its source, `src/claude_code_hooks_daemon/install/templates/core/SessionModes.core.md`,
and copy it over the deployed file; `tests/unit/install/test_core_doc_deployment.py`
fails when the two differ.

## Where the depth lives in this repository

The core document is the canonical home for what each mode does, how it is
entered and ended, and what it suppresses. The implementation detail lives
beside the code that owns it:

- The ccy supervisor's BLOCKED gate, its `noop:` reasons and the fail-closed
  read of an unreadable session-modes file:
  [development/CcySupervisor.md](development/CcySupervisor.md#session-modes-a-blocked-session-gets-no-work-driving-prompt).
- The `session_mode_indicator` segment's sources and render-path cost:
  [Architecture/StatusLine.md](Architecture/StatusLine.md).
- Per-handler options and defaults (`goal_loop_detector`, `focus_mode_trigger`,
  `failsafe_cron_blockage_suppressor`, `auto_continue_stop`):
  [docs/guides/HANDLER_REFERENCE.md](../docs/guides/HANDLER_REFERENCE.md).
- The design (state inventory, suppression matrix, rulings): Plan 00501
  (`bin/hooks-daemon find-plan 501`).
