# Issue #60 parts 1 and 2: cron stop back-off and pause hint

## Finding

Both defects were real. `verdict_for_missing_crons` (`utils/cron_enforcement.py`, shared by `cron_stop_enforcer` and its SubagentStop twin) denied on every stop while an unpaused job was missing, and `render_missing_crons_reason` never named `cron-pause`.

## Convention followed

Other Stop/SubagentStop blocks are one-shot per chain: `subagent_report_size_blocker` and `subagent_report_path_verifier` do not fire when `stop_hook_active` is set, and `auto_continue_stop` uses `utils.stop_hook_helpers.is_stop_hook_active`. I used that helper (both wire spellings).

## Policy

- First stop with an unpaused missing job: DENY, unchanged, now ending with the `hooks-daemon cron-pause <job> --reason "<the owner's words>"` escape.
- Re-entry (`stop_hook_active`) with an unpaused missing job: ALLOW plus a `logger.warning` naming the job and the pause command.
- Not silent forever: the flag resets on the next fresh stop chain, where the check runs again.
- Deviation from the brief: no loud advisory in the response. `HookResult._format_stop_response` (core/hook_result.py) deliberately drops non-blocking context on re-entry (the v3.31.0 loop-breaker), so context on the re-entry ALLOW would never be delivered. The log line is the loud part. A counted re-entry allowance was rejected: no existing handler does it.
- The paused-job path is unchanged.

## Changes

- `src/claude_code_hooks_daemon/utils/cron_enforcement.py`: pause line in the deny reason, re-entry branch.
- `src/claude_code_hooks_daemon/handlers/stop/cron_stop_enforcer.py`: `get_claude_md()` guidance.
- `CLAUDE/development/IssueSdlc.md`: corrected the claim that every stop names the pause.
- Release note 186.
- Tests in `tests/unit/handlers/stop/test_cron_stop_enforcer.py`.

## TDD

Red before the fix: 4 failed, 27 passed (pause not named; re-entry denied under both spellings; no warning logged). After: 116 passed across the five touched cron test files (enforcer, subagent twin, cron_enforcement, whitespace, pause).

## Unverified

- Real Claude Code behaviour of `stop_hook_active` across a multi-turn chain was not observed live; it rests on the existing handlers' documented reading.
- With several missing jobs the reason names the first job id in the pause example only.
- The pre-existing acceptance test (`stop_hook_active: False`) was not re-run.
