# Plan 00450: release skill mandates forbidden subagent acceptance gate

**Status**: Not Started
**Created**: 2026-09-21
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

Two skill documents give directly opposed instructions for the same gate.
`.claude/skills/release/invoke.sh:168-169` tells the agent running Step 12 that
the process "Groups tests into batches (3-5 tests each)" and "Spawns parallel
Haiku agents to execute ALL batches concurrently".
`.claude/skills/acceptance-test/invoke.sh:14` states that "Sub-agent testing is
FORBIDDEN - agents cannot reliably test hooks (context limits, no Write tool,
lifecycle events don't fire)", and `SKILL.md` adds that the v2.9.0 incident
proved async agents create race conditions with release gates.

The contradiction is not cosmetic, because the two documents disagree about a
BLOCKING release gate. An agent that reads the release skill and follows it
literally runs the acceptance gate by the method the acceptance skill forbids
by name — and the failure mode is not a loud error. Sub-agents have no Write
tool, so every `PreToolUse:Write` probe fails for a reason that has nothing to
do with the handler under test, and lifecycle events do not fire in a sub-agent
at all. A gate that cannot observe what it claims to observe reports a verdict
indistinguishable from a real one.

This was hit during the v3.66.0 release: the two documents were read in the
same session, the conflict was noticed, and it was resolved by judgement
(follow the more specific and newer skill) rather than by the documents. That
resolution is not durable — the next agent re-derives it, or does not.

## Goals

- One documented method for executing the Step 12 acceptance gate, with the
  other document pointing at it rather than restating it.
- The stale parallel-Haiku procedure removed from `release/invoke.sh`, not
  merely contradicted elsewhere.
- A test that fails if the two skills drift back into disagreement about
  sub-agent execution.

## Non-Goals

- Changing which method is correct. Main-thread sequential execution is the
  decided answer (`acceptance-test/SKILL.md`, v2.10.0); this plan makes the
  documents agree with it, and does not reopen it.
- Reworking the acceptance harness itself.
- Auditing every other skill's `invoke.sh` for drift — Plan 00324 built the
  contract test for that class and is Complete; this plan closes the two
  skills it left unresolved.

## Prior Art

- **Plan 00324** (Complete) — established that skill `invoke.sh` procedures
  drift from their `SKILL.md`, and built a contract test against it. It fixed
  several drifted skills but left `release` and `acceptance-test` carrying this
  active contradiction. Verify why these two were excluded before assuming the
  existing contract test can simply be extended to cover them.
- **Plan 00044** (Cancelled) — proposed the parallel-Haiku design that
  `release/invoke.sh` still describes. Its cancellation is the reason those
  lines are stale, and is useful context for the rewrite.

## Tasks

### Phase 1: Establish the true state

- [ ] ⬜ **Task 1.1**: Read both `invoke.sh` files and both `SKILL.md` files in
  full and record every place either describes HOW the acceptance gate
  runs, including `CLAUDE/development/RELEASING.md` Step 12, which both
  skills defer to as the source of truth. The contradiction may be
  three-way rather than two-way.
- [ ] ⬜ **Task 1.2**: Read Plan 00324's contract test and determine whether
  these two skills are excluded from it, and if so why. That exclusion is
  the reason the drift survived, and is the thing to fix.

### Phase 2: Make the documents agree

- [ ] ⬜ **Task 2.1**: RED — a test asserting that no skill `invoke.sh`
  instructs sub-agent or parallel-Haiku execution of acceptance tests.
  It must fail against the current tree on `release/invoke.sh:169`.
- [ ] ⬜ **Task 2.2**: GREEN — replace the batching/parallel-Haiku procedure in
  `release/invoke.sh` with a pointer to the acceptance-test skill, so one
  document owns the method.
- [ ] ⬜ **Task 2.3**: Confirm `RELEASING.md` Step 12 names the same method,
  and fix it if not.

## Success Criteria

- [ ] `grep -niE "haiku|parallel" .claude/skills/release/invoke.sh` returns no
  instruction to execute acceptance tests that way.
- [ ] The new test fails when the forbidden procedure is reintroduced into any
  skill's `invoke.sh`.
- [ ] Exactly one document describes how the Step 12 gate executes; the others
  link to it.
- [ ] Full QA green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00450-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found during the v3.66.0 release, filed after the tag.
