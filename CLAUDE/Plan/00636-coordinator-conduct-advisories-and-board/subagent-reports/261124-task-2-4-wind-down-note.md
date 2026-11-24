# Task 2.4 report: s8 wind-down (advise-only part)

Spec on disk: one PLAN.md Goals line ("stops around running background agents stop failing") and one 00630 DESIGN.md section 19 row ("109 failed stops around background agents"). Nothing names which denies those were, or what the mode does. Only the advise-only subset was built.

Built:

- `utils/wind_down.py`: reads the Stop payload's `background_tasks`. Absent, empty or malformed means no information. Only a dict with `status == "running"` counts. Ids are echoed only when they are a `str` of safe characters (`[A-Za-z0-9._:@/-]`), truncated to 64 characters, with at most 5 listed and "and N more" after that. Any other id is counted but never pasted. Never raises.
- `auto_continue_stop`: Branch 4 (`R-STOP-NO-REASON`) appends the note after the goal-ledger challenge, on every fire (dynamic content, outside the disclosure ladder). The gate is `coordinator_advisory_armed`. The seat probe runs only when a running task is reported, and a raising probe counts as armed. `_team_seat` is injected by the registry as for the other seat handlers.
- The note offers `STOPPING BECAUSE: N background tasks are still running; their completion notices resume this session.` Tests pin that it matches neither `_declares_human_blocked` nor `owner_wait_stop_guard._waiting_re`, and that it carries no rule id. The line is indented in the note, so `_declaring_lines` ignores it. It also names `ListAgents`/`TaskStop`, because a finished teammate is still listed as running.

Why no new handler: `HookResult._format_stop_response` sends ALLOW context as `additionalContext`, and Claude Code continues the turn on any non-empty context. A standalone Stop advisory would therefore itself cause a failed stop. The note rides only on a refusal that is already being given. Nothing is newly allowed or refused.

Checked, not changed: `branch_stop_guard` already hands over branches owned by running agents (`branch_stop_gate._hand_over`: queue record, git lock or `.claude/worktrees/` directory). `idle_workable_issue_stop_gate` already counts a running `background_tasks` entry as in flight.

Open (owner): which denies made up the 109 failed stops; whether wind-down should be a real session mode with entry and exit; and which guards, if any, it may relax. Any relaxation loosens a guard.

Paperwork: release note 098. No new handler, option or config key, so there is no config-changes entry, and the generated docs are unchanged (regenerated, no diff).

Tests: `tests/unit/utils/test_wind_down.py` and `tests/unit/handlers/stop/test_auto_continue_stop_wind_down.py` were red first (import error), then green. The whole `tests/unit/handlers/stop` passed (679 passed, 1 known xfail). The broad targeted directories are listed in the PR.
