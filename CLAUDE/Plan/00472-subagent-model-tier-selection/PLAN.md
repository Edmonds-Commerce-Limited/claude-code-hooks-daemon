# Plan 00472: subagent model tier selection

**Status**: In Progress
**Created**: 2026-09-25
**Owner**: dev
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #58

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

**Workflow fan-out (the costliest case).** The owner saw a Fable main thread
launch a `Workflow` of 60 parallel Fable agents. One ultracode run can spend
millions of tokens in minutes that way. Work that fans out 60 wide is almost
always Sonnet-level. The `Workflow` tool call is a PreToolUse event whose
input carries the whole script. So, unlike an ad-hoc `Agent` call, the daemon
can see the fan-out and each `agent()` call's model option BEFORE any agent
starts. Phase 2 covers it.

**Kept separate from 00471, cross-linked.** The owner asked whether to merge
this into the token-economy plan (00471). Both plans have a brainstorm and an
owner decision list of their own. 00471 bounds how MUCH context an agent
spends; this plan governs WHICH model spends it, and how many agents a
workflow launches at that tier. The owner can still merge them with one
message. The decisions are listed side by side in each plan's Task 1.2.

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

- [x] ✅ **Task 1.1**: A fresh subagent brainstorms what the daemon can
  observe, which signals mark a task as safe for a lower tier, levers from
  advisory to enforcing, the false-positive risks, and how this interacts
  with Plan 00471. Report:
  `subagent-reports/260925-p472-brainstorm-opus-5-5.md` (levers T0 to T7,
  and seven owner decisions in its section 6).
- [ ] ⬜ **Task 1.2**: The owner picks the levers and thresholds from the
  brainstorm and the Phase 2 research.

### Phase 2: Workflow fan-out

- [x] ✅ **Task 2.1** (report:
  `subagent-reports/260925-p472-workflow-fanout-sonnet-5.md`; PreToolUse on
  `Workflow` is the only catch point, since a script's `agent()` calls fire no
  PreToolUse(`Agent`) and SubagentStart names no parent run): Research what PreToolUse(`Workflow`) exposes (the
  inline script, `scriptPath`, a named workflow), how an `agent()` call's
  model is chosen when it has no `model` option, and whether workflow agents
  fire SubagentStart. Then design levers: a static count of the script's
  fan-out, an explicit `model` required on fanned-out `agent()` calls when the
  session runs the top tier, and a fan-out ceiling per tier, advisory or
  deny. Report into `subagent-reports/`.
- [ ] ⬜ **Task 2.2**: Capture one real PreToolUse(`Workflow`) payload before
  any handler is built; the shape is undocumented and nothing captured it yet.
  A workflow may only run when the owner opts in, so this waits on the owner
  running one small workflow with payload capture on.

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
