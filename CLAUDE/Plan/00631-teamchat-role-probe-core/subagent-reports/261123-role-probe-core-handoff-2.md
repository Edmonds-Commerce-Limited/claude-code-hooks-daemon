# Plan 00631 handoff 2: whoami contract reconciled; stamp, CLI and config left

Supersedes `261123-role-probe-core-handoff.md` (its item 1 named
`TEAMCHAT_MEMBERSHIP`, which is dropped). Branch
`plan-00631-teamchat-role-probe-core`, head `e25dd3b9f`, pushed, origin/main
merged in (merge commit `8b2545729`). Worktree
`/workspace/.claude/worktrees/agent-a4fed6cbe399e3308-e6f56464`.

## Done

- `utils/teamchat_seat.py` now matches the final contract
  `{"v":1,"teams":[{team,handle,role,duty}]}`: input is
  `SessionSignals(runtime, kit)` (`from_environ`); argv
  `$KIT/bin/teamchat whoami --json` with `TEAMCHAT_RUNTIME` in the overlay;
  no runtime / detection off / exit 69 / empty `teams` => ABSENT; kit unset,
  relative path, not found, timeout, exit 65, other non-zero, bad JSON,
  missing or unknown `v`, wrong shape => UNRESOLVED (unknown, armed).
  `role_in`, `duty_in` (name, `"unknown"`, or None), `any_duty`,
  `duty_unknown`, `duplicate_teams`; role coordinator with duty host reads as
  role unknown. Run-directory path probe removed (invariant 5); a behavioural
  test patches open/stat/lstat/scandir and asserts nothing is touched.
- `utils/team_role_gate.py`: `duty_gate` added for acts that name no team.
- Fixtures `tests/support/teamchat.py`; tests
  `tests/unit/utils/test_teamchat_seat.py`, `test_team_role_gate.py`:
  84 passed; ruff, black, mypy clean.
- DESIGN.md sections 2 and 3 record the contract, `fe67f23c3`, exit 69.
  PLAN.md ticks re-applied (1.1 in progress, 1.2, 2.1, 3.1, 3.2 done).

## Left

1. Task 2.2 stamp. Fields `HookInputField.TEAMCHAT_RUNTIME = "teamchat_runtime"`,
   `TEAMCHAT_KIT = "teamchat_kit"` in `constants/protocol.py` (comment like
   `SESSION_HOSTNAME`). init.sh: beside the hostname block (~line 4356), set
   each only if not already on the payload. server.py: stamp beside
   `_stamp_session_hostname` (call site ~line 2097), never overwrite. Prefer
   ONE `/proc/<pid>/environ` read for hostname and teamchat; existing tests
   patch `server._peer_hostname` and `server.hostname_override_of_process`
   (`test_event_socket_session_hostname.py`,
   `test_event_socket_hook_event_name_enrichment.py`,
   `test_event_socket_status_raw_text.py`, `test_event_socket_listeners.py`),
   so a refactor must update those seams. Add
   `SessionSignals.from_hook_input`. Add INPUT-ALLOWLIST.yaml entries
   (`contracts/claude-code-hooks/`) for both fields, modelled on
   `hooks_daemon_hostname`. Forwarder test precedent:
   `tests/integration/test_forwarder_jq_free.py` ~line 340.
2. Task 2.3: diagnostic CLI (reads its own environment; prints the context or
   "absent" with the reason) and `team_seat` config block with only
   `detection` (auto|off) and `resolve_ttl_seconds` (60); mirror the most
   recent top-level config block's sites (model, validation, example, docs,
   UPGRADES manifests).
3. Holding-area entries (grep `UNRELEASED`) for the config block, the two
   payload fields and the CLI.
4. Task 1.1 remainder: F44 merge hash, exit 65 confirmation, and the proof
   that the daemon shares the session's mount namespace and user (else run
   `whoami` hook-side and stamp its JSON).

## Open

- A well-formed role outside `coordinator|worker|probe` is carried as
  declared and switches nothing on (not mapped to unknown).
- Whether NO_SEAT should arm B2 guards is Q5/Q9; `guards_armed` is False.
