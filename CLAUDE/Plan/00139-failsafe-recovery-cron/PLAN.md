# Plan 00139: Failsafe Recovery Cron

**Status**: In Progress (handler shipped & live-verified; awaiting deep-review polish via Plan 00140)
**Created**: 2026-06-23
**Owner**: Claude (Opus)
**Priority**: Medium
**Recommended Executor**: Sonnet (advisory handler(s) + tests)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

While a plan is **being executed**, a **non-durable hourly failsafe recovery
cron** runs as a safety net: if work stalls on an *external* factor (Claude API
overload, rate limits, 5-hour usage limits, network failure) the cron fires
(only while the REPL is idle) and tells the agent to resume. It is explicitly
**not** a heartbeat — the agent must never wait for it; work proceeds at full
speed until something external actually blocks it.

The daemon cannot create crons (`CronCreate` is an agent-side tool), so its role
is **advisory across the plan lifecycle**:

1. **Plan creation** → advise/enforce that recovery-cron setup is part of the
   plan itself, and prompt the agent to create the cron.
2. **Plan progress-update** → ensure a recovery cron is actually running while
   the plan executes (re-prompt if missing) — the real "while executing" signal.
3. **Plan completion** → prompt the agent to tear the cron down (`CronDelete`).

A **reminder-tracking / cooldown** mechanism prevents the advisory from spamming
context on every progress edit.

See `context.md` for the problem statement, today's trigger, and the cron
introspection findings.

## Decisions (resolved with user 2026-06-23)

- **D1 — Durability: NON-durable (session-only).** User experience is that
  durable crons are unreliable and arguably undesirable. The handler's whole
  purpose is to ensure a cron is *running during execution* and *cleaned up on
  completion*; a durable cron would both defeat the need for the handler and
  risk stale firing in unrelated later sessions. Crons are **created
  non-durable**. The daemon MAY still read a durable one if present (to avoid
  double-prompting), but the supported/created mode is non-durable.
- **D2 — Dedup: in-session reminder tracking, not disk introspection.** Because
  created crons are non-durable they are invisible on disk, so dedup is about
  **not spamming the reminder**: track that we have advised (per plan / with a
  cooldown) and stay quiet until the cooldown lapses or the cron is known gone.
  The agent uses `CronList` to confirm a recovery cron exists before creating a
  duplicate.
- **D3 — Set one up now: YES (done).** Live non-durable hourly cron
  `e243f234` (at :23) created this session as a dogfood against today's flaky
  API. The agent will NOT wait for it.
- **D4 — Trigger: new PostToolUse handler(s) on the plan lifecycle**, not an
  extension of the PreToolUse `plan_workflow` handler. Triggers on plan
  creation, progress-update, and completion (see Overview).

## Goals

- Ensure a non-durable hourly recovery cron is running **for the duration of an
  active plan**, and is **removed on completion**.
- On plan creation, advise/enforce that cron setup is captured **as part of the
  plan** (an explicit execution-protocol element), and prompt cron creation.
- On plan progress-update, verify a recovery cron is running; re-prompt if not.
- Canonical recovery-cron prompt that (a) resumes externally-paused work, (b) is
  a no-op when work is already proceeding, (c) waits only on human-input blocks,
  (d) never acts as a heartbeat, (e) self-deletes when the plan is done.
- Reminder cooldown/tracking so progress edits don't spam context.

## Non-Goals

- The daemon will **not** create, list, or delete crons itself (agent-side only).
- **Not** a heartbeat / pacing / progress-ping mechanism.
- **Not** durable cron creation, and **not** a process supervisor — it recovers
  an idle-but-alive session, it cannot relaunch a fully-exited Claude process.
- No new external dependencies.

## Context & Background

Key facts (full detail in `context.md`):

- `CronCreate(durable:false)` (the chosen mode) → in-memory only, dies with the
  session; `durable:true` → `.claude/scheduled_tasks.json` (gitignored).
- Recurring crons auto-expire after 7 days (fire once more, then delete).
- Crons fire only while the REPL is idle → they cannot interrupt active work.
- Daemon cannot see in-memory crons on disk; the agent checks via `CronList`.

## Architecture

### Trigger detection (PostToolUse, plan-dir scoped)

Detect the three lifecycle moments from Write/Edit (and `mkplan.bash` Bash) to
`PLAN.md` under the configured plan directory:

- **Creation**: new `PLAN.md` written, or `mkplan.bash` invoked.
- **Progress-update**: edit to an existing `PLAN.md` that touches task status
  (`⬜`/`🔄`/`✅`) or the `## Notes & Updates` section.
- **Completion**: `**Status**: Complete` written, or a `git mv` of the plan
  folder into `Completed/`.

Open implementation choice: **one handler with three branches** vs **a small
handler per moment**. Lean: one cohesive `recovery_cron_advisor` handler keyed
by detected lifecycle phase (single SRP = "manage the recovery-cron advisory
across a plan's life"), with phase detection in a tested helper.

### Reminder tracking / cooldown

- Per-plan, in-memory cooldown counter (mirrors `critical_thinking_advisory`):
  after advising, suppress further cron reminders for that plan for N
  progress-updates (configurable), unless a completion is detected.
- Note: the shared daemon serves multiple sessions; key tracking by plan
  identity (folder/number) so the cooldown is meaningful and not cross-session
  leaky. Fail-safe: if unsure, advise (a redundant reminder is cheaper than a
  missing cron).

### Guidance injected

- **Creation**: "Recovery-cron setup is part of executing this plan. Create a
  non-durable hourly recovery cron now (CronCreate, durable:false, off-:00
  minute), and record it in the plan. Do NOT wait for the cron — keep working."
- **Progress-update**: "Confirm your failsafe recovery cron is still running
  (CronList). If it isn't, recreate it. Keep working."
- **Completion**: "This plan is complete — delete its recovery cron
  (CronDelete) so it doesn't fire in unrelated future work."

### Canonical recovery-cron prompt (as deployed live this session)

> **FAILSAFE RECOVERY CHECK (automated hourly safety net — NOT a heartbeat).**
> If your most recent work on the active plan/task was interrupted by an
> *external* factor (Claude API error/overload, rate limit, 5-hour usage limit,
> network failure) and is now resumable, resume it immediately and carry it to
> completion. If you are blocked **only** on human input, do nothing and keep
> waiting. If work is already proceeding normally, this is a **no-op** — do not
> interrupt, restart, or duplicate anything in flight. Never treat this as a
> heartbeat or pacing signal: between checks, continue at full speed until an
> external factor actually stops you — waiting for the cron is an own goal. When
> the plan is complete and no resumable work remains, delete this cron
> (CronDelete).

## Tasks

### Phase 1: TDD — lifecycle detection

- [x] ✅ Tests: detect creation vs progress-update vs completion from
  Write/Edit/Bash inputs against the plan dir (positive + negative).
- [x] ✅ Implement the phase-detection helper to green.

### Phase 2: TDD — advisory handler

- [x] ✅ Tests: each phase injects the correct guidance; cooldown suppresses
  repeat reminders; completion always advises teardown. (49 unit tests)
- [x] ✅ Implement `recovery_cron_advisor` (PostToolUse, advisory, opt-in via
  `get_default_enabled()`).
- [x] ✅ `get_claude_md()` documents recovery-vs-heartbeat + the canonical prompt.
- [x] ✅ `get_acceptance_tests()` covers the three phases.

### Phase 3: Config + docs

- [x] ✅ Register handler (init_config.py, handler_profiles.py, hooks-daemon.yaml
  dogfooded enabled, yaml.example opt-in); config-changes manifest staged
  (`UNRELEASED/config-changes/v3.27.0.yaml`, `recommended: true`).
- [x] ✅ Update PlanWorkflow.md: recovery cron is part of plan execution; the
  "never wait for the cron" rule.

### Phase 4: Verify

- [x] ✅ Daemon restart RUNNING; live probe of all three lifecycle advisories
  (creation/completion fire correctly; non-plan write is a clean no-op).
- [x] ✅ Full QA `./scripts/qa/llm_qa.py all` → 13/13 on main.

### Phase 5: Deep-review polish (via Plan 00140) — MUST-FIX this session

- [ ] ⬜ **Cooldown unit mismatch (confirmed live dogfood bug, HIGH):** the
  progress cooldown compares `get_data_layer().history.total_count` against
  `_PROGRESS_COOLDOWN_EVENTS = 20`, but `controller.py:635` records ONE history
  entry per *matched handler per event*, so `total_count` grows by several per
  tool call. Effective cooldown ≈ 2–4 PLAN.md edits, not 20 → the progress
  advisory re-fires almost every edit (observed firing twice within ~3 tool
  calls while editing this very plan). This is the context-spam the cooldown was
  meant to prevent. **Fix:** replace the global-`total_count` cooldown with a
  deterministic per-plan progress counter owned by the handler (advise on the
  1st progress event for a plan, then every Nth), with TDD. The
  `critical_thinking_advisory` `total_count` pattern does NOT transfer to a
  PostToolUse handler that fires on consecutive edits.
- [ ] ⬜ `_TASK_STATUS_ICON_RE` mixed character class (includes `⚠️`, which is
  not a task-status icon, and stuffs multi-codepoint emoji into a `[]` class).
- [ ] ⬜ Redundant `[&&]` character class in `_NOTES_SECTION_RE` (should be `&`).

## Dependencies

- Builds on the plan-handler cluster (`plan_workflow`, `plan_number_helper`,
  `validate_plan_number` — hardened in Plan 00138).

## Success Criteria

- [ ] Plan creation surfaces cron-setup-as-part-of-plan guidance + prompts cron
  creation (non-durable, hourly).
- [ ] Plan progress-update ensures the cron is running, without context spam.
- [ ] Plan completion prompts cron teardown.
- [ ] Canonical cron prompt enforces recover-not-heartbeat + self-teardown.
- [ ] 13/13 QA; daemon restart verified; acceptance tests pass.

## Risks & Mitigations

| Risk                                          | Impact | Probability | Mitigation                                                                                               |
| --------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------------------------------- |
| Agent treats cron as heartbeat (waits for it) | High   | Med         | Rule in BOTH advisory text and cron prompt; reinforce in PlanWorkflow.md                                 |
| Reminder spam on every progress edit          | Med    | High        | Per-plan cooldown counter (mirrors critical_thinking_advisory)                                           |
| Cron left running after plan done             | Med    | Med         | Completion trigger advises CronDelete; cron prompt self-deletes when no work remains                     |
| Cross-session cooldown leak (shared daemon)   | Low    | Med         | Key tracking by plan identity; fail-safe to advise when unsure                                           |
| Non-durable cron lost on full session crash   | Med    | Med         | Accepted per D1; recovers the common idle-but-alive case; new session re-advised on next progress-update |

## Notes & Updates

### 2026-06-23

- Plan created; introspection findings in `context.md`.
- Decisions D1–D4 resolved with the user: non-durable crons; in-session reminder
  tracking (not disk dedup); live cron created now; new PostToolUse lifecycle
  handler. Refined from one-shot-on-creation to a three-moment lifecycle
  (create → ensure-while-executing → teardown-on-complete).
- Live dogfood cron `e243f234` (hourly at :23, non-durable) created this session.
- Handler built by sub-agent on worktree, merged to main (commit `09bc085`,
  fast-forward), daemon restarted RUNNING, QA 13/13 on main, all three lifecycle
  advisories live-probed OK, pushed. Daemon auto-regenerated CLAUDE.md handler
  guidance (`d58f05e`).
- **Live dogfood confirmation**: editing this PLAN.md (marking tasks ✅) tripped
  the handler's PROGRESS-update advisory in production, which correctly reminded
  to confirm the recovery cron is running. `CronList` confirmed `e243f234` still
  active; continued working without waiting (recover-not-heartbeat upheld).
- Residual polish (regex smells) deferred to the Plan 00140 deep-review pass.
