# Handoff: 00636 Task 2.1a owner-wait Stop guard (branch plan-00636-stop-guard)

Worktree: `/workspace/.claude/worktrees/agent-a6d1fc9ca72dfceff-148fd440` (venv built; run tools as
`$(ls -d untracked/venv-*)/bin/<tool>`, `nice -n 19`, targeted only; `git` commands must be plain
single commands, not chained with venv calls).

## Done (pushed unless noted)

1. `src/claude_code_hooks_daemon/utils/owner_wait_check.py` + `tests/unit/utils/test_owner_wait_check.py`
   (32 tests green): pure decision. `OwnerThread` (SEAT_QUESTION / OWNER_STARTED / FOREIGN), `BusPost`
   (tri-state `from_self`, `notifying`; `thread_root` = m.thread target; `relation_readable`;
   `in_reply_to` carried only to prove it does not count), `stale_threads(snapshot, now, window_seconds)`,
   `has_meaningful_body`, `printable_thread_id` (Q<n> bare, `$event` shlex-quoted, anything else None).
   Seat question: needs qualifying post within window. Owner-started: closed by one qualifying post at or
   after its start, no window. Future-stamped posts never count.
2. `src/claude_code_hooks_daemon/utils/owner_wait_bus.py` + test (4 green): `OwnerWaitBus` Protocol,
   `BusUnreadable(reason)`, `TeamchatOwnerWaitBus`: `read()` runs nothing and returns unreadable (no
   verified history contract with notify flag / m.thread; `pingbus history --help` shows only
   --team/--limit/--room, no JSON); `bump_command()` -> `teamchat bump <ids>` or `teamchat bump --waiting`
   when any id is untrusted. R11 itself unverified.
3. COMMITTED, NOT PUSHED: `tests/unit/handlers/stop/test_owner_wait_stop_guard.py` (red: handler absent).

## Left

- Write `src/claude_code_hooks_daemon/handlers/stop/owner_wait_stop_guard.py` to the red tests. Model on
  `idle_workable_issue_stop_gate.py`. Seams the tests use: `_resolve_seats(signals) -> SeatContext`
  (default: `SeatContextResolver.from_config(load_config_cached(...).team_seat)`, cached), `_bus`,
  `_clock`, `_window_minutes: object` (default `DEFAULT_WINDOW_MINUTES = 30`, provisional until Task 1.1;
  invalid = bool/non-int/\<=0/>1440 -> default + WARNING containing "window_minutes").
  `matches()`: not usage-paused, not `stop_hook_active`, waiting (session_policy blocked, or
  `_declares_human_blocked`, or own regex on `_declaring_lines` text after `STOPPING BECAUSE:`:
  "waiting on/for ... owner|human|user|answers|replies|decision|input", "awaiting ..."), and
  `SessionSignals.from_hook_input(...).runtime` non-empty (no probe otherwise). `handle()`: per
  `context.teams_held()`, `role_gate(..., role="coordinator")`; only APPLIES reads the bus (ROLE_UNKNOWN
  untouched per plan); `BusUnreadable` or exception -> WARNING log naming the reason, allow. Deny text: ids
  only (via `printable_thread_id`), ONE bump command per team, says a post counts only if notifying and an
  unreadable notify flag/relation does not count, never echoes bus bodies. Non-terminal, scope MAIN.
- Register: `HandlerID.OWNER_WAIT_STOP_GUARD` (constants/handlers.py), `Priority.OWNER_WAIT_STOP_GUARD = 3`
  (free Stop slot, below auto_continue 10), `RuleID.STOP_OWNER_WAIT_UNBUMPED = "R-STOP-OWNER-WAIT-UNBUMPED"`,
  `handlers/stop/__init__.py`, `.claude/hooks-daemon.yaml` + `.example`, `daemon/init_config.py`,
  `docs/guides/HANDLER_REFERENCE.md`, `docs/guides/CONFIGURATION.md`, `get_claude_md`,
  acceptance tests, release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/0NN-...md`, config-changes
  `v3.77.0.yaml`. Grep every surface of `idle_workable_issue_stop_gate` and mirror. Then run targeted
  tests incl. `tests/integration/test_stop_chain_terminal_shadowing.py`,
  `test_all_handlers_response_validation.py`, `tests/unit/config/`.
- Plan: tick 2.1a only; annotate 2.1 partly done (AskUserQuestion deny out of scope); Task 1.2 (asking
  fedora-desktop.1 about notify flag, m.thread exposure, wake coalescing) NOT sent from this thread; leave
  unticked. Journal via `mkplan.bash --journal`. PR (do not merge); flag for owner: production adapter is
  inert (fail-open) until teamchat documents history fields; re-entry allowed once per stop chain.
