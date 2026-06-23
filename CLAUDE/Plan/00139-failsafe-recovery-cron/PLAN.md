# Plan 00139: Failsafe Recovery Cron

**Status**: Not Started (design — awaiting user decisions on open questions)
**Created**: 2026-06-23
**Owner**: Claude (Opus)
**Priority**: Medium
**Recommended Executor**: Sonnet (single new advisory handler + tests)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Promote a workflow where, **once a plan is created**, the agent sets up an
**hourly failsafe recovery cron** — a safety net that resumes work stalled by
external factors (API failures, rate limits, 5-hour usage limits), but which is
explicitly **not** a heartbeat and must never be waited upon.

The daemon cannot create crons (`CronCreate` is an agent-side tool), so its role
is **advisory**: a new PostToolUse handler detects plan creation and injects
guidance instructing the agent to create the recovery cron idempotently. The
guidance — and the cron prompt itself — both carry the "do NOT treat this as a
heartbeat; keep working until externally blocked" rule.

See `context.md` for the problem statement, today's trigger, and the cron
introspection findings.

## Goals

- Detect plan creation and advise the agent to create one hourly failsafe
  recovery cron per project (idempotent — never spam one-per-plan).
- Provide a single canonical recovery-cron prompt that (a) resumes externally
  paused work, (b) is a no-op when work is already proceeding, (c) waits when
  the only blocker is human input, (d) never acts as a heartbeat.
- Make the daemon dedup-aware: do not re-advise if a recovery cron already
  exists (introspection via `.claude/scheduled_tasks.json` for durable crons).
- Encode the "must not wait for the cron" rule so the agent keeps working apace.

## Non-Goals

- The daemon will **not** create, list, or delete crons itself (agent-side only).
- **Not** a heartbeat / pacing / progress-ping mechanism.
- **Not** a process supervisor — it cannot relaunch a fully-exited Claude
  process; it recovers an idle-but-alive session (and, if durable, re-arms on
  the next session start).
- No new external dependencies.

## Context & Background

Key facts (full detail in `context.md`):

- `CronCreate(durable:true)` → `.claude/scheduled_tasks.json` (gitignored);
  `durable:false` (default) → in-memory only.
- Recurring crons auto-expire after 7 days.
- Crons fire only while the REPL is idle → cannot interrupt active work.
- Daemon can read durable crons from disk; cannot see in-memory crons except via
  observing `CronCreate`/`CronList`/`CronDelete` hook events.

## Open Decisions (need user input — questions raised alongside this plan)

### D1: Cron durability — durable vs session-only

- **A (recommended): `durable: true`** — survives full session restart; daemon
  can introspect/dedup across sessions via `scheduled_tasks.json`. Cost: a
  persistent gitignored file; risk of a *stale* recovery cron firing in a later
  session after the work is done (mitigation: recovery prompt self-checks "is
  there resumable work? if not, no-op and consider CronDelete").
- **B: session-only (default)** — simplest, no stale crons, dies with session.
  Still recovers the common case (API flake / limit while session stays alive &
  idle). Cost: no cross-session dedup; daemon cannot introspect it.

### D2: Daemon dedup via `scheduled_tasks.json`

- **A (recommended):** handler reads `scheduled_tasks.json`; if a recovery cron
  (matched by a stable marker token in its prompt) is present, stay silent.
  Only valuable if D1=A (durable).
- **B:** no daemon dedup; always advise, rely on the agent's own judgement +
  the advisory text ("create one if you haven't already").

### D3: Set up a recovery cron NOW for this live session

- Given today's flaky API and ongoing large work, optionally create the recovery
  cron immediately as a live dogfood, independent of building the handler.
- **A:** yes, create it now. **B:** no, build the feature first.

### D4: Trigger surface

- **A (recommended):** new PostToolUse handler matching BOTH (i) Write/Edit to
  `CLAUDE/Plan/NNNNN*/PLAN.md` and (ii) Bash invoking `mkplan.bash`, deduped to
  one advisory per session.
- **B:** extend the existing `plan_workflow` (PreToolUse) handler instead.
  Rejected unless preferred — PreToolUse fires *before* creation, and mixing
  cron-advice into a different-SRP handler dilutes it.

## Recommended Architecture (pending D1–D4)

A new advisory PostToolUse handler `recovery_cron_advisor`:

- **matches()**: a plan was just created (Write/Edit to a `PLAN.md` under the
  configured plan dir, or a `mkplan.bash` Bash call). Opt-in via
  `get_default_enabled()` per project policy.
- **handle()**: if dedup enabled and a recovery cron already exists (durable
  store read), return no-op context. Otherwise inject guidance:
  - Instruct the agent to call `CronCreate` with the canonical hourly recovery
    prompt and recommended schedule (an **off-:00 minute**, e.g. `17 * * * *`,
    per CronCreate guidance to avoid fleet-wide :00 pileups).
  - Carry the **"do not wait for this cron; keep working until externally
    blocked"** rule prominently.
- **get_claude_md()**: document the handler, the recovery-vs-heartbeat
  distinction, and the canonical cron prompt.

### Canonical recovery-cron prompt (draft)

> **FAILSAFE RECOVERY CHECK (automated hourly safety net — NOT a heartbeat).**
> If active work was interrupted by an *external* factor (API error/overload,
> rate limit, usage/5-hour limit, network failure) and is now resumable, resume
> it immediately and carry it to completion. If you are blocked **only** on
> human input, do nothing and keep waiting. If work is already proceeding
> normally, this is a **no-op** — do not interrupt, restart, or duplicate
> anything. Never treat this check as a heartbeat or pacing signal: between
> these checks you must continue working at full speed until an external factor
> stops you. (Recurring crons auto-expire after 7 days — if you are still mid-
> project, re-arm this cron.)

## Tasks

### Phase 0: Decisions

- [ ] ⬜ Resolve D1–D4 with the user.
- [ ] ⬜ (If D3=A) create the live recovery cron for the current session.

### Phase 1: TDD — handler

- [ ] ⬜ Write failing tests: `matches()` positive (PLAN.md write, mkplan.bash
  bash) and negative (non-plan writes, plan edits that are not creation).
- [ ] ⬜ Write failing tests: `handle()` injects the canonical guidance; dedup
  path returns no-op when a recovery cron is present (if D2=A).
- [ ] ⬜ Implement `recovery_cron_advisor` to green.
- [ ] ⬜ `get_claude_md()` + acceptance tests via `get_acceptance_tests()`.

### Phase 2: Dedup / introspection (if D1=A & D2=A)

- [ ] ⬜ Utility to read `.claude/scheduled_tasks.json` and detect a recovery
  cron by stable marker token (fail-safe: absent/malformed file → advise).
- [ ] ⬜ Tests for present / absent / malformed store.

### Phase 3: Config + docs

- [ ] ⬜ Register handler; decide opt-in default; add config-changes manifest
  entry (opt-in feature → `recommended: true`) for the next release.
- [ ] ⬜ Update PlanWorkflow.md / CLAUDE.md guidance on the recovery cron and
  the "never wait for it" rule.

### Phase 4: Verify

- [ ] ⬜ Daemon restart RUNNING; live probe of the advisory.
- [ ] ⬜ Full QA `./scripts/qa/llm_qa.py all` 13/13.

## Dependencies

- Builds on the plan-handler cluster (`plan_workflow`, `plan_number_helper`,
  `validate_plan_number` — hardened in Plan 00138).

## Success Criteria

- [ ] Creating a plan reliably surfaces the recovery-cron advisory (deduped).
- [ ] Canonical cron prompt enforces recover-not-heartbeat semantics.
- [ ] Daemon introspects durable crons for dedup (if D1/D2=A).
- [ ] 13/13 QA; daemon restart verified; acceptance tests pass.

## Risks & Mitigations

| Risk                                          | Impact | Probability | Mitigation                                                                      |
| --------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------- |
| Agent treats cron as heartbeat (waits for it) | High   | Med         | Rule stated in BOTH advisory text and cron prompt; reinforce in PlanWorkflow.md |
| Stale durable cron fires after work done      | Med    | Med         | Recovery prompt self-checks for resumable work; no-op + optional CronDelete     |
| 7-day expiry on long projects                 | Med    | Med         | Cron prompt instructs re-arming; re-advised on later plan activity              |
| Advisory spam (one per plan)                  | Low    | Med         | Dedup to one-per-project/session                                                |

## Notes & Updates

### 2026-06-23

- Plan created. Introspection findings recorded in `context.md`. Architecture
  recommended (advisory PostToolUse handler + optional durable-cron dedup).
  Open decisions D1–D4 raised with the user before implementation.
