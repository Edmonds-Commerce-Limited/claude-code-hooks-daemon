# Plan 00140: Deep Code Review & Fix (Workflow-Orchestrated)

**Status**: In Progress
**Created**: 2026-06-23
**Owner**: Claude (Opus)
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Dynamic Workflow (fan-out review → adversarial verify → Opus fixers)

## Overview

A deep, multi-agent round of code review and remediation across the daemon
source, orchestrated with the **dynamic Workflow tool** and **Opus sub-agents**.
The existing QA gate (format/lint/types/95%-coverage tests/security/magic-values

- custom checks) already passes, so this round targets the class of issues QA
  does **not** catch: logic bugs in `matches()`/`handle()`, handler false
  positive/negative risks, SOLID/DRY/YAGNI smells, missing edge-case handling,
  error-handling correctness, and doc-vs-code drift.

This plan has a **second purpose**: it is the heavy, long-running session work
that **dogfoods the failsafe recovery cron** (Plan 00139, live cron `e243f234`).
While the review/fix workflow runs, the cron is the safety net against today's
flaky Claude API and any 5-hour usage-limit stall; we then **actively
introspect** the cron to confirm it behaves as a recovery net (not a heartbeat).

## Goals

- Run a fan-out review across the codebase by dimension and subsystem, with
  **adversarial verification** of every finding to kill false positives.
- Remediate confirmed issues via Opus fixer sub-agents using TDD, isolated so
  parallel fixes don't collide.
- Integrate fixes: full QA `./scripts/qa/llm_qa.py all` 13/13 + daemon restart
  verified before each merge to main.
- Dogfood Plan 00139's recovery cron under real long-running load and **confirm
  via introspection** it recovers stalled work and is never treated as a
  heartbeat.

## Non-Goals

- Not a rewrite or architecture change — surgical fixes to real defects only.
- No suppressions, no workarounds (project ZERO-tolerance standards apply).
- Not a coverage-number chase — fix real bugs/smells, not vanity metrics.

## Approach (dynamic Workflow)

1. **Scope** (inline scout): enumerate review targets — handler files by event
   type, plus `daemon/`, `config/`, `install/`, `qa/`, `utils/` — to build the
   work-list before fan-out.
2. **Review** (fan-out): one reviewer per dimension × subsystem slice. Dimensions:
   correctness/logic bugs, handler match/handle alignment & false-pos/neg,
   security antipatterns, SOLID/DRY/magic-values/YAGNI, error handling/fail-fast,
   type safety, doc-vs-code drift (`get_claude_md()` accuracy vs behaviour).
   Structured findings (schema: file, line, dimension, severity, claim, fix).
3. **Verify** (adversarial): independent Opus skeptics try to REFUTE each finding;
   keep only findings that survive majority verification. Dedup across reviewers.
4. **Fix** (Opus fixers, worktree-isolated): one fixer per confirmed cluster,
   TDD (RED→GREEN), returns branch + SHA + QA result.
5. **Integrate** (main thread): merge each fixer branch, run full QA + daemon
   restart verification, push. Checkpoint commits throughout.

## Tasks

### Phase 1: Scope & launch

- [ ] 🔄 Build the review work-list (subsystems × dimensions).
- [ ] ⬜ Launch the review→verify Workflow (Opus agents, dynamic).

### Phase 2: Triage

- [ ] ⬜ Collect verified findings; rank by severity; group into fix clusters.

### Phase 3: Remediate

- [ ] ⬜ Dispatch Opus fixer agents (worktree-isolated, TDD) per cluster.
- [ ] ⬜ Merge each fix to main with QA 13/13 + daemon restart verified.

### Phase 4: Cron dogfood & introspection

- [ ] ⬜ Confirm cron `e243f234` present throughout (CronList).
- [ ] ⬜ Observe/confirm recovery semantics: if any external stall occurs, the
  cron resumes work; confirm it is NOT waited upon (work continues apace).
- [ ] ⬜ Record findings on the cron's real-world behaviour to feed Plan 00139.

## Dependencies

- Plan 00139 (failsafe recovery cron) — live cron `e243f234` already running;
  this plan exercises and validates it.

## Success Criteria

- [ ] Every confirmed finding fixed (or explicitly deferred with reason) — no
  silent drops; truncation/scope limits logged.
- [ ] Full QA 13/13 + daemon restart RUNNING after each merge.
- [ ] Cron introspection confirms recover-not-heartbeat behaviour, recorded for
  Plan 00139.

## Notes & Updates

### 2026-06-23

- Plan created as the heavy dogfood load for Plan 00139's recovery cron.
  Workflow-orchestrated (dynamic) per user direction: deep review/fix with Opus
  sub-agents for fixing. Launch follows the 00139 handler build landing on main.
