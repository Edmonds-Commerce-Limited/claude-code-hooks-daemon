# Plan 00631 handoff: role probe core and role gate done; stamp, CLI and config left

Branch `plan-00631-teamchat-role-probe-core` (pushed; not merged).

## Done

- `src/claude_code_hooks_daemon/utils/teamchat_seat.py`: the one teamchat v2
  module. `probe_seat_context(membership, *, detection_enabled, runner, path_probe, timeout)` and `SeatContextResolver` (per-membership TTL cache,
  injected clock). `SeatContext.role_for_team(team)` answers a
  `TeamRoleAnswer` (`kind` NO_TEAM / NO_SEAT / UNKNOWN / DECLARED,
  `holds_role()`, `guards_armed`). Absent runs nothing and logs nothing; a set
  signal that cannot be read is UNRESOLVED with a `ProbeReason` category (never
  output text in logs). Credential path refused; EACCES-safe path probe via
  `path_predicates.path_exists`. `Timeout.TEAMCHAT_WHOAMI = 2`.
- `src/claude_code_hooks_daemon/utils/team_role_gate.py`: `role_gate(hook_input, context, *, team, role)` -> APPLIES / ROLE_UNKNOWN / NOT_APPLICABLE; main
  thread only via `handler_scope.acts_as_main_thread`; no approval verdict.
- Tests: `tests/unit/utils/test_teamchat_seat.py`,
  `tests/unit/utils/test_team_role_gate.py`; fixtures (assumed shape header)
  in `tests/support/teamchat.py`. Targeted tests, ruff, black, mypy, bandit
  (module only) green.

## Left

1. Task 2.2 payload stamp: new `HookInputField` (e.g. `teamchat_membership`)
   in `constants/protocol.py`; stamp `TEAMCHAT_MEMBERSHIP` in `init.sh` beside
   the `hooks_daemon_hostname` block (~line 4357) and in `daemon/server.py`
   beside `_stamp_session_hostname` (~line 308, called ~line 2097) using
   `utils/cron_hosts.process_environ(pid)`; never overwrite; precedent tests
   `tests/unit/daemon/test_event_socket_session_hostname.py`.
2. Task 2.3: diagnostic CLI and the `team_seat` config block (detection, TTL).
3. Pending-release holding-area entries for config block, payload field, CLI.
4. Task 1.1: reconcile fixtures and parser with fedora-desktop's merged JSON;
   record the shape in umbrella DESIGN.md.

## Open questions

- Is `duty` the design's seat kind (host/container), or a separate axis? No
  `seat_kind` is exposed until that is known.
- Is `TEAMCHAT_MEMBERSHIP` an absolute path? The probe assumes so (a relative
  value answers `membership_not_a_path`, unknown).
- A set signal with zero seats is treated as unknown (armed); confirm.
- Whether NO_SEAT (in a team session, acting on another team) should arm B2
  guards is Q9/Q5; `guards_armed` is False for it today.
- `status.json` is not read: its location and row shape are unknown.
