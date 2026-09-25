# Plan 00472: subagent model tier selection

**Status**: In Progress
**Created**: 2026-09-25
**Owner**: dev
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner has seen that a main thread running on the top model tier (Fable)
often gives its subagents Fable too. The top tier makes sense for the
orchestrator, which carries the whole context and makes the judgement calls.
But much delegated work (a bounded fix, a targeted test run, a verification
pass, a search) is safe on Sonnet or Opus, at a fraction of the cost. The
same logic runs one tier down. An Opus orchestrator should hand routine work
to Sonnet, and escalate a task to Fable only when it really needs it.

The daemon sees every `Agent` tool call. That includes its `model` argument,
its `subagent_type`, and the agent definition's own default model, plus the
transcript usage that follows. So it can measure which tier each delegation
got, and advise when the choice looks mismatched to the task. This plan asks
how to monitor that choice and nudge it toward lower tiers where they are
safe, without ever blocking a delegation that really needs the top tier.

This is the model-choice twin of
[Plan 00471](../00471-subagent-token-budget-protection/PLAN.md). That plan
bounds how much context a subagent spends; this one looks at which model spends
it. The owner marked it not urgent. It goes into the normal pipeline.

## Goals

- Record, per session, the model each subagent was dispatched on, whether it
  was explicit or inherited, and the orchestrator's own model.
- Surface a clear picture of tier choice (for example a session report or
  status-line signal).
- Advise the orchestrator at dispatch time when a routine-looking task is
  going to the top tier, naming the cheaper tier that fits.
- Keep it advisory unless the owner decides otherwise. A needed escalation
  must never be blocked.

## Non-Goals

- Choosing the model automatically for the agent.
- Blocking a delegation on tier alone.
- Changing Claude Code's own default-model behaviour.

## Tasks

### Phase 1: Brainstorm

- [ ] 🔄 **Task 1.1**: A fresh subagent brainstorms what the daemon can
  observe, which signals mark a task as safe for a lower tier, levers from
  advisory to enforcing, the false-positive risks, and how this interacts
  with Plan 00471. Report into `subagent-reports/`.
- [ ] ⬜ **Task 1.2**: The owner picks the levers and thresholds from the
  brainstorm.

## Success Criteria

- [ ] Every subagent dispatch in a session is recorded with its model and
  how that model was chosen.
- [ ] A routine task dispatched to the top tier draws an advisory naming a
  cheaper tier, and a justified escalation draws none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00472-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened at the owner's request.
