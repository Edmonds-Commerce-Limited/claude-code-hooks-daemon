STOPPING BECAUSE: the review is done. The verdict is REQUEST CHANGES: 2 critical, 4 major and 6 minor findings.

**I did not create the report file you asked for.** I have no Write tool, and my operating rules say not to write report `.md` files and to return findings as text. Writing it through a Bash heredoc would also skip the project's Write/Edit content guards. The full report is below. `subagent_report_persistence` should save this reply to disk, and you can copy it to `/workspace/CLAUDE/Plan/00479-subscription-usage-monitor-and-ceiling/subagent-reports/261002-p479-pause-gate-review-opus.md`.

**Evidence script (keep it for the plan folder):** `/workspace/untracked/scratch/p479-review/probe.py`. It runs against the branch source, extracted with `git archive` into `/workspace/untracked/scratch/p479-review/tree/`. Run it with `untracked/venv-workspace-py311-81c29529/bin/python untracked/scratch/p479-review/probe.py`. Checks P1–P7 below refer to its output.

# Code Review: Plan 00479 Phase 4 — usage pause gates (`main...origin/worktree-p479-pause-gate`, head c082efbbc)

Reviewed: 35 files, +2841/−37. Found 2 CRITICAL, 4 MAJOR, 6 MINOR.

## Critical

### C1. `ToolSearch` is denied, so a paused session may be unable to call the cron tools (Confidence 80)
**Location:** `utils/usage_pause_gate.py:72-74`, `handlers/pre_tool_use/usage_pause_tool_gate.py:77-85`
- **Problem:** CronCreate, CronDelete and CronList are *deferred* tools. The project's own research says so (`CLAUDE/Plan/Completed/00293-.../RESEARCH-context-fat.md:382`: "Deferred built-ins (11 tools: CronCreate/Delete/List …) — full schema loads only via ToolSearch"). Any `ToolSearch` call while paused gets `deny_and_halt` (probe P7: `ToolSearch matched (deny_and_halt): True`).
- **When it bites:** whenever the cron schemas are not already in context. That certainly includes after the supervisor's pause `/compact`, which is exactly when a "still over" resume tick arrives. The model reaches for ToolSearch, the turn halts, and no resume cron is created.
- **Result:** the resume cron has already fired and is gone, so nothing wakes the session again.
- **Fix:** add `ToolName.TOOL_SEARCH` (new constant in `constants/tools.py`) to `PAUSE_ALLOWED_TOOLS`. Name it in the directives ("load the cron tools with ToolSearch if needed") and add a test.

### C2. No owner override: the human is locked out for up to about 7 days, and the documented escape does not work (Confidence 90)
**Location:** `handlers/user_prompt_submit/usage_pause_gate.py:150-154` (hold runs before any ceiling check), `:88-95` (rule `verbose`); builder report "Residual risks" item 6
- **Problem:** `_hold` denies every prompt, the owner's included, until `resume_at + 3600`. For a `seven_day` breach that can be days away.
- **Wrong advice:** the rule text says "To lift the ceiling for this host, edit `hosts:` … and restart the daemon", and the builder repeats it. That is false. `_hold` never re-reads the config, so the record keeps holding (probe P5: no `hosts:`, live record, owner prompt → `deny`).
- **Only real escapes:** deleting `untracked/context-sidecar/<sid>.usage-paused` by hand, or typing the undocumented `[tick:usage-resume]` sentinel.
- **Fix:**
  1. In the hold path, re-run `_breaches()` on every held prompt. It is cheap and already used. If there is no ceiling, no snapshot or no breach, clear the record and allow. This also covers a missed or late resume tick (see M2).
  2. Add an owner command, e.g. `hooks-daemon usage-pause clear [--session]`.
  3. Correct the rule text and docs.

## Major

### M1. Read errors fail closed: a broken record path can deny every tool call and trap every Stop (Confidence 85)
**Location:**
- `utils/usage_pause_gate.py:215-231` (only `RuntimeError` is caught)
- `utils/usage_pause.py:225` (`path.exists()`)
- tags at `usage_pause_tool_gate.py:70` and `usage_pause_stop_gate.py:74-79`
- stand-down call at `stop/cron_stop_enforcer.py:144` (a SAFETY+BLOCKING handler)
- `usage_pause_gate.py:128-129` (`latest_usage` OSError not caught)

**Problem:**
- On Python 3.11, `Path.exists()` re-raises `EACCES`. Probe P2: `read_usage_pause` raised `PermissionError`, and the tool gate's `matches` raised too.
- `core/chain.py:1124-1170` turns any exception from a SAFETY+BLOCKING handler into a **DENY**. The tool gate runs `matches` on every tool call in every session, ceiling or not, so one unreadable record path denies all tools project-wide.
- The same raise now sits at the top of `cron_stop_enforcer.matches`. Its crash path bypasses the `stop_hook_active` escape, so every Stop, re-entries included, is denied: a stop loop.
- In `auto_continue_stop` (not a SAFETY handler) the same raise just skips the handler, which quietly switches it off.
- On a host that has a ceiling, an `OSError` from `latest_usage` crashes the prompt gate and denies every prompt. `usage_indicator` already catches this error; the gate does not.
- This breaks the brief's rule that a broken record must never pause anything or switch off a safety handler.

**Fix:**
- Make `active_usage_pause` total: catch `OSError`, and broadly any exception, log a warning and return None.
- Use `try: read_text() except FileNotFoundError` instead of `exists()`.
- Catch `OSError` in `_default_usage_loader`.
- Add tests that the tool gate, the stop gate and `cron_stop_enforcer` all allow when the record read raises.

### M2. The one-shot cron is pinned to a date, so it can land in the past and fire next year; the Stop gate never checks the schedule (Confidence 75)
**Location:** `utils/usage_pause_gate.py:69,184-201`; `handlers/stop/usage_pause_stop_gate.py:100`
- **Problem:** `resume_at` is `resets_at + 120 s`, and the cron is `m h d M *`. If the reset is close, e.g. a 5h window over the ceiling with 10 s left, the model has about 2–3 minutes for CronList, N × CronDelete, CronCreate and maybe a Stop-gate round. If that minute passes, the expression next matches a year later (probe P3: `resume_at=now+5s → 26 11 2 10 *`).
- A time-zone mismatch between the daemon process and Claude Code fails the same way. The builder flags this as unverified.
- The Stop gate accepts any single cron carrying the sentinel. `SessionCron.schedule` is available but never compared. The session then sleeps behind a cron that will not fire for a year.
- **Fix:**
  - Floor the resume time at `now + lead` (e.g. 10 min), or do not enter a pause when the deciding reset is less than the lead away.
  - In the Stop gate, require `crons[0].schedule == resume_schedule(pause.resume_at).cron`.
  - The C2 re-evaluate-on-hold fix lets the next prompt recover after a missed tick.

### M3. A pause only starts on `UserPromptSubmit`, so a session kept going by Stop-hook continuations never pauses (Confidence 75)
**Location:** `handlers/user_prompt_submit/usage_pause_gate.py:146-155`; `usage_pause_stop_gate.py:87-89` (it only matches an existing record)
- **Problem:** Unattended sessions here mostly continue through Stop blocks (`auto_continue_stop`, `cron_stop_enforcer`) and long turns, not new prompts. Neither path checks the ceiling, so such a session runs straight past it.
- **Fix:** run the same `_breaches` → `_record` entry in the Stop gate (or PreToolUse). The Stop gate can deliver the directive as its deny reason, which does reach the model. Add tests.

### M4. A pause record has no upper bound on `resume_at`, so a corrupt or hand-edited record pauses the session indefinitely (Confidence 80)
**Location:** `utils/usage_pause.py:95-105,141-142`; supervisor mirror `.claude/ccy/claude-supervise.py:2401-2403,2432`
- **Problem:** probe P4: a record with `resume_at` 10 years out is live. The new gates give such a record real effect: the prompt hold, the tool halt, and a silenced supervisor.
- **Fix:** reject `resume_at - paused_at > 7 days + RESUME_MARGIN_SECONDS + slack` in `_validation_error` and in the supervisor's `_parse_usage_pause`, and extend the pinning test.

## Minor

1. **Missing session id creates a pause anyway.** `usage_pause_gate.py:79,148`: a payload with no `session_id` writes a pause under `"unknown"`. Every other reader uses `""` and fails open. Such a record holds all later id-less prompts, and a supervisor with `own_sessions=None` will pick it up. *Fix:* use `""` and skip both entry and hold.
2. **Told to resume while tools stay blocked.** `usage_pause_gate.py:225-234`: if `clear_usage_pause` fails, the model is still told "USAGE PAUSE LIFTED … continue", but the tool gate keeps halting every call until expiry. *Fix:* return the still-paused directive, or a "lift not recorded" note, when the clear fails.
3. **Other handlers act on prompts that were dropped.** `usage_pause_gate.py:109`: the gate is non-terminal, so every other UserPromptSubmit handler still runs on a prompt the model never sees. Example: `failsafe_cron_blockage_suppressor` clears the awaiting-human marker and resets cadence on a dropped owner prompt. *Fix:* end the chain on a hold deny, or make those handlers skip denied prompts.
4. **Broken docstring table.** `utils/cron_tick.py:11`: the new row ``` ``[tick:usage-resume]`` ``` is 24 characters, wider than the 21-character column. *Fix:* widen the table.
5. **Duplicated failsafe schedule.** `utils/usage_pause_gate.py:87`, `_FAILSAFE_SCHEDULE_HINT = "47 * * * *"`, repeats `failsafe_cron_session_advisor.py:71`. *Fix:* move it to one shared constant.
6. **Record read twice per Stop.** `usage_pause_stop_gate.py:89,94` reads the record in both `matches` and `handle`. *Fix:* cache it per event, as `recovery_cron_advisor` does with `_cached_phase`.

## Answers to your questions
1. **Pausing without a ceiling or on stale data:** entry needs a `hosts:` ceiling for `effective_hostname`, and windows past `resets_at` read as absent (`usage_snapshot.py:135-137`). No pause starts without both. Holding is another matter: it happens without either (C2, M4), and a pause record can start under the `"unknown"` session (minor 1).
2. **Deadlocks:** the Stop gate never traps the session. It allows an absent `session_crons` and allows on re-entry. The real failures are C1, M1's stop loop, M2, and the owner lockout in C2.
3. **Resume cron:** the sentinel is recognised, and `failsafe_cron_blockage_suppressor.py:408` lets the tick through. A tick that arrives while still over the ceiling refreshes the record and re-directs the model correctly. The cron itself has the M2 problem, and the still-over path hits C1.
4. **Tool names:** `CronList`, `CronDelete` and `CronCreate` are the real names; `ToolSearch` is missing (C1). Subagents share the session id, so they are halted as well, which is sensible. Agent-team teammates have their own session ids and are not covered.
5. **Stand-downs:** all six check the one session-scoped predicate before anything else. They fail open on a missing record but not on a raised error (M1).
6. **Supervisor interaction:** the field names, `.usage-paused` suffix, `context-sidecar` directory, window set and 3600 s grace all match. Each still-over refresh gets a new `paused_at`, so the supervisor compacts again each time, which is acceptable.
7. **Tests:** nothing covers C1, C2, M1–M4 or minor items 1–3.

## Good work
Every decision reads the same single predicate. Expired windows read as absent. The Stop gate cannot trap a session. The design decision on how the entry directive is delivered is documented. Fail-open paths log distinct messages.

## Still to check in the Task 4.8 live probe
- Whether a supervisor-injected `/compact` passes through UserPromptSubmit. If it does, `_hold` would deny it.
- The 90-second early-fire jitter on one-shot crons scheduled at :00 or :30, against the 120 s margin.