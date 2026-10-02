STOPPING BECAUSE: round 4 (R3-1, R3-2) is implemented and tested; targeted QA is green.

# Plan 00479 pause gate, round 4 (Sonnet)

Branch `worktree-p479-pause-gate`, after `git merge --no-ff origin/main` (clean, no conflicts).

## R3-1: subagents (owner ruling: finish, never start more, main winds them up)

- `handlers/pre_tool_use/usage_pause_tool_gate.py`: a subagent's call is never matched, so never denied or halted, whether or not the session is paused. A subagent over the ceiling still calls `try_start_pause`, so the record is written and the main thread pauses on its next call. The session is added to `_entered`, so the main thread's first call after a subagent-started pause is a plain deny carrying the directive (no halt); later calls halt. `_SUBAGENT_REASON` and the plain-deny-a-subagent branch are deleted.
- Allow-list (`utils/usage_pause_gate.PAUSE_ALLOWED_TOOLS`): `Agent` and `Task` (both in `SUBAGENT_DISPATCH_TOOL_NAMES`, the only two dispatch names in the codebase) are NOT on it, so a new subagent is denied for the main thread. Added `SendMessage` and `TaskStop`: without them the directive's wind-up step would itself be denied. `ToolName.SEND_MESSAGE` and its `ToolNameLiteral` entry added to `constants/tools.py` (it did not exist).
- Directive (entry only): "do not start new subagents ... Let running subagents finish; you may SendMessage them to wrap up and report. Stop idle or finished teammates with TaskStop; do not stop one that is still working." The existing test that every tool the directive names is allowed still passes.

## R3-2: host-zone-independent resume

- Resume cron is now recurring `*/10 * * * *` (`RESUME_CRON_SCHEDULE`), `recurring: true`.
- `usage_pause_gate` prompt handler, `_resume`: a tick before `resume_at` is a DENY at zero cost and does not read usage; the first tick at or after it re-checks usage as before (lift, or still over). Still-over keeps the existing cron: the directive says "Do NOT create another cron" and to stop.
- Stop gate: "exactly the one resume cron" now also requires `is_resume_schedule(schedule)`; any other schedule (including the old pinned minute) is refused with the reason.
- Lift directive: step 1 is now an explicit `CronDelete` of the recurring resume cron (it would otherwise keep ticking every ten minutes), before the crons are re-established.
- Deleted: `resume_schedule`, `ResumeSchedule`, `_pinned_fire_time`, `schedule_fires_in_window`, `MAX_FIRE_AFTER_RESUME_SECONDS`, `PauseEnvironment.tz`, the handler `_tz`, every `tz=` parameter, and the matching stale entry in `scripts/qa/error_hiding_exclusions.json` (the audit reported it stale). New: `resume_time_text` (always `YYYY-MM-DD HH:MM UTC`), `is_resume_schedule`, `resume_is_due`. The status line keeps showing local `HH:MM` (display only).
- R3-5 confirmed gone: `refresh_resume`, `renew_pause` and the `max(..., now + margin)` floor in `build_pause` are deleted. A stale `resume_at` is harmless now: the next tick is due and re-checks usage. `RESUME_MARGIN_SECONDS` (120s after the reset) stays.

## Tests (red first)

Red evidence before any source change: `test_usage_pause_stop_gate.py` failed to import (`RESUME_CRON_SCHEDULE` missing); the other three changed files gave 33 failed, 152 passed.

Added or rewritten:

- Tool gate: subagent over ceiling writes the record and is not matched (any tool); below ceiling and owner override write nothing; main's next call carries the directive without a halt, then halts; a subagent in an already paused session is not matched; `SendMessage`/`TaskStop` are left alone.
- Gate utils: `RESUME_CRON_SCHEDULE` shape (no hour/day/month), zone maths gone, `resume_time_text` UTC, `is_resume_schedule`, `resume_is_due` at the boundary, `Agent`/`Task` off the allow-list, wind-up directive wording, lift directive deletes the resume cron before re-establishing, still-over directive.
- Prompt gate: early tick dropped (DENY, no context, record kept, usage not read), tick one second early dropped, tick at `resume_at` lifts, lift names the resume cron.
- Stop gate: pinned minute and other recurrences refused, the schedule accepted whatever `resume_at`, no renewal or clearing at Stop.

Tests that pinned the old behaviour were replaced and are called out in the commit message: pinned-minute and zone tests (`TestResumeSchedule`, `TestScheduleVerification`, `TestTimeZoneIsStatedInTheDirective`), the refresh and renew tests, the subagent-denied-plainly and subagent-never-starts tests, and the existing resume tests that fired a tick against a record whose `resume_at` was still ahead (now use a due record).

## QA (targeted)

- ruff: pass. black `--check --target-version py311`: pass (after running black on two files). mypy on the 11 changed source and test files: no issues.
- `audit_error_hiding.py`: pass (after removing the stale exclusion). `check_input_contract.py`: pass. `run_pyright_check.py --json`: exit 0.
- pytest: all usage-pause test files, `tests/unit/constants`, and the doc and handler-reference integration tests: 1025 passed, 1 failed. The failure is `tests/integration/test_claude_md_guidance_coverage.py::test_no_handler_is_unclassified` for `MergeQaAdvisorHandler`, which arrived with the `origin/main` merge and is unrelated to this branch.

## Docs touched

`docs/guides/HANDLER_REFERENCE.md` (tool gate, stop gate, prompt gate), the 213 release note, `.claude/HOOKS-DAEMON.md` row 9, and one phrase in Plan 00479 Task 4.1.

## What remains of R3-3 to R3-6

- R3-3 (override marker: cap on read, unreadable marker active forever, no agent-write guard): untouched, follow-up.
- R3-4 (`_entered` keyed per session, can race across executor threads): untouched. This round also feeds `_entered` from a subagent's call, so the same race applies there; in practice it only decides which parallel call carries the directive.
- R3-5: gone with the pinned minute (see above).
- R3-6 (exact-equality read-back that deletes on a mismatch): untouched, follow-up. The CLI `except` around `current_breaches` in `usage-pause clear` is also untouched.

One behaviour to know: a resume tick that arrives with no live record and usage under the ceiling still gives the lift directive, so a model that forgets to `CronDelete` the recurring cron is re-told every ten minutes until it does.
