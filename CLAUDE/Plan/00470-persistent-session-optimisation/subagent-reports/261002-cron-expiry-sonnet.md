# Plan 00470 Tasks 2.1, 2.2, 3.4: cron expiry refresh (report)

Branch `worktree-p470-cron-expiry`. Not merged.

## Task 3.4 (no bug)

A teammate or sub-agent stop cannot write the lead's `[awaiting-human]` marker on main:

- `auto_continue_stop` is the only caller of `write_marker` (pinned by an AST scan).
- It is scoped `MAIN`, and the chain refuses a payload carrying `agent_id` (a teammate's is 30 characters, a sub-agent's 17, per `core/handler_scope.py`) before `matches()` runs.
- `tests/unit/handlers/stop/test_awaiting_human_marker_scope.py` drives the real `HandlerChain`: a main-thread stop arms the marker (positive control), a teammate-shaped Stop, a sub-agent Stop and a `SubagentStop` event do not, and with the scope forced to `ALL` the teammate stop does arm it (so the negatives are not vacuous). It was GREEN on first run, so nothing needed fixing.
- Teammates are not distinguished from sub-agents by any Stop field beyond `agent_id`; `TeammateIdle` has `teammate_name` but is a different event that nothing here handles.

## Task 2.1: `cron_record_keeper`

- PostToolUse, priority 36, default on, silent, fails open. State in `cron-records.json` (daemon untracked dir), written atomically with `blockage_marker.write_json_atomically` plus a module lock for the read-modify-write.
- Record: `session_id`, `cron_id`, `schedule`, `prompt_hash` (sha256 of the normalised words, never the text), `created_at`. A `recurring: false` create is not recorded.
- **Unverified**: the `CronCreate` `tool_response` shape is not in the contracts. The id is read from a mapping key (`id`, `cronId`, `jobId`, ...) or `id: <token>` text; an unreadable result records nothing and the enforcer stamps the job at its next Stop. Task 1.2 should confirm the shape.
- **Liveness signal** (no session registry exists): a record is pruned on every write when older than 7 days (the cron cannot exist) or future-dated, and `forget_missing` drops a session's records that its own `session_crons` no longer lists. A session that vanishes leaves its records for at most 7 days.
- `get_claude_md()` returns `None`, recorded as exempt in `test_claude_md_guidance_coverage.py` (the agent-facing instruction lives in `cron_stop_enforcer`'s guidance and deny reason).

## Task 2.2: refresh in both enforcers

- Shared judgement in `utils/cron_refresh.py` (`judge_declared_crons`); both handlers call it. `cron_enforcement.matching_session_crons` and `normalise_prompt` were extracted so matching and fingerprinting share one definition.
- Option `refresh_after_days`, default 6, valid above 0 and below 7 (otherwise the default, with a warning). Default justification: one day under the expiry leaves room for 24 hourly ticks, some of which may be dropped while the session waits on a human, and the platform documents "7 days" without saying how it counts.
- Age >= `refresh_after` denies, naming `CronDelete <id>` and the `CronCreate` schedule and prompt. A job with no record is stamped now and allowed. The youngest copy of a duplicated job decides.
- Deferrals: usage pause (the handlers' `matches()` already returns False, unchanged), `cron-pause` (a paused job is not refreshed), and one deny per stop chain (`stop_hook_active` allows and logs). The `[awaiting-human]` marker is deliberately NOT consulted: the existing enforcer never read it, and it silences ticks, which is exactly when a job ages toward expiry unnoticed.
- Priority 7 and `terminal=False` are unchanged and asserted for both handlers.

## Wiring

`HandlerID.CRON_RECORD_KEEPER`, `Priority.CRON_RECORD_KEEPER = 36`, `init_config` template, `.claude/hooks-daemon.yaml.example`, this repo's `.claude/hooks-daemon.yaml` (enabled), regenerated `.claude/HOOKS-DAEMON.md`, config-changes entries (handler and option) in `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.68.0.yaml`, release note 217.
