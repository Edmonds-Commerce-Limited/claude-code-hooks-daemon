# N380 regressions on main (6 failing tests)

1. Priority bands: `write_protected_paths` shipped at 22, between the Safety (10-20) and Code Quality (25-35) bands. Moved to 18 (Safety, a PreToolUse write blocker). Changed in `constants/priority.py`, `daemon/init_config.py`, dogfood yaml, yaml example, `HANDLER_REFERENCE.md` (3 places), `v3.70.0.yaml`, regenerated `.claude/HOOKS-DAEMON.md`.
2. Raw literals: `plan_fact_check_feed._checker_dispatch_prompt` read `"tool_name"` / `"tool_input"` (not from the two merges; landed with N359). Now `HookInputField.TOOL_NAME` / `TOOL_INPUT`.
   3 and 4. Opt-in template: `write_protected_paths` ships `enabled: false`; added it to `_EXPECTED_OPT_IN_CONFIG_KEYS` (a legitimate list extension).
3. Peer pid: the server stamps `hooks_daemon_peer_pid` after stripping any caller value (kept, security property). The test now drops `HookInputField.PEER_PID` from the received payload before comparing to the sent one; every other key must still arrive unchanged.
4. Option injection: the sentinel is not a valid `paths` value, so `validate_options` withheld it. Added `("write_protected_paths", "paths"): ["zzqx/protected/**"]` to `_VALID_NON_DEFAULTS`.
