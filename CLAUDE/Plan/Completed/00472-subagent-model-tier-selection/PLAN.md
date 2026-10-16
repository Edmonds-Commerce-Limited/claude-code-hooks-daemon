# Plan 00472: subagent model tier selection

**Status**: Complete
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
- [x] ✅ **Task 1.2**: The levers and thresholds are picked from the
  brainstorm and the Phase 2 research. Decided by a Fable ruling under the
  owner's delegation, not by the owner: [RULINGS-fable.md](RULINGS-fable.md).
  The `CLAUDE_CODE_SUBAGENT_MODEL` flip (D1) and T7 stay with the owner.

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
- [x] ✅ **Task 2.2** (234bffa3f): Build the one PreToolUse(`Workflow`)
  handler defensively and make it its own payload probe: on the first
  `Workflow` call of a session it writes the `tool_input` key names and value
  types (never the script text) to `payload-capture/workflow-shape.json`, and
  allows any shape it cannot parse with an `unparsed` verdict. Confirming it
  against a real payload is
  [Plan 00530](../../00530-subagent-tier-enforcement-follow-up/PLAN.md) Task 1.1
  and does not block this plan.

### Phase 3: Build (RULINGS-fable.md section 4)

- [x] ✅ **Task 3.1** (59cbd6a4f): `resolve_model_family` and the rank table
  in `utils/model_tiers.py`, with the Explore cap rule.
- [x] ✅ **Task 3.2** (3d959a9e5): dispatch-source and role classifier,
  `utils/dispatch_tier.py`.
- [x] ✅ **Task 3.3** (59c01ac0f): dispatch tier rows in the shared spend
  ledger, the PostToolUse `resolvedModel` join (`dispatch_model_recorder`) and
  the `downgraded` flag at SubagentStop.
- [x] ✅ **Task 3.4** (ee5299367): `hooks-daemon tiers`.
- [x] ✅ **Task 3.5** (317c7bac2): `subagent_tier_advisor`.
- [x] ✅ **Task 3.6** (234bffa3f): `workflow_fanout_advisor`.
- [x] ✅ **Task 3.7** (59cbd6a4f): the spend segment's per-family live counts
  read the shared rank table.
- [x] ✅ **Task 3.8**: docs page, `HANDLER_REFERENCE.md`, manifest, release
  note 079, 00280 cross-reference, baseline copy and the dogfood run (JOURNAL
  26-10-16). The issue #58 comment is drafted; posting it moved to
  [Plan 00530](../../00530-subagent-tier-enforcement-follow-up/PLAN.md) Task 1.4.

## Success Criteria

Per RULINGS-fable.md section 5.

- [x] 01: every `Agent` dispatch has a ledger row (type, name, model
  parameter, definition model, source, predicted family, role, then
  `resolvedModel`); a fixture session proves 0 unjoined rows.
- [x] 02: the classifier returns the 472-B section 1.2 label for the fixture
  matrix, and labels a `python-developer` "fix review findings" dispatch fix.
- [x] 03: `hooks-daemon tiers` prints the by-source, by-model and by-role
  tables, the `CLAUDE_CODE_SUBAGENT_MODEL` line and the downgraded-agent list
  from fixtures, with a mid-run swap's per-model request counts.
- [x] 04: the tier advisory's fire/silent matrix and the floor advisory
  (unit-tested); the acceptance run through a real dispatch in this repo.
  Tests: `tests/unit/handlers/pre_tool_use/test_subagent_tier_advisor.py`
  `TestFires` and `TestSilent` (including
  `test_floor_on_an_explicit_sonnet_code_reviewer`,
  `test_role_floor_on_an_inherited_sonnet_security_check`), passing on main at
  b1d6397f4. Live: an explicit-sonnet `hooks-daemon-plan-dedupe-scout`
  dispatch drew the TIER advisory naming haiku (JOURNAL 26-10-16).
- [x] 05: no handler in this plan returns a deny; tests assert allow across
  the matrix.
- [x] 06: the Workflow advisor reports N and M per fixture, resolves an
  `args`-driven fan-out exactly, treats a script-computed list as unknown and
  at the ceiling, says "at least N", allows an unparsable `tool_input` with one
  `unparsed` verdict, and writes the shape sidecar once per session.
- [x] 07: the status segment shows per-family live counts from fixture
  sidecars.
- [x] 08: `HANDLER_REFERENCE.md`, `docs/guides/SUBAGENT_MODEL_TIERS.md` and
  the config-changes manifest describe every new handler, option and the CLI;
  the pending-release holding area records the release-bound consequences
  (release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/079-subagent-model-tiers-measured-and-advised.md`);
  Plan 00280's PLAN.md carries the cross-reference.
- [x] 09: the baseline is copied
  (`subagent-reports/260925-p472-tiers-baseline.json`); the dogfood journal
  entry (26-10-16, "dogfood run") cites a `hooks-daemon tiers` run, the two
  dispatch ledger rows and a real `subagent-tier-advisor` verdict.
- [x] 10: the implementation summary for GitHub issue #58 is drafted for the
  coordinator to post; posting it and the close decision moved to
  [Plan 00530](../../00530-subagent-tier-enforcement-follow-up/PLAN.md) Task 1.4.
- [ ] 11: targeted QA green on the work branch; the coordinator's full gate
  green before merge. The coordinator's full gate runs in the release
  (RELEASING.md Step 1b); left for the coordinator to tick.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00472-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened at the owner's request.
- Scheduling (owner ruling): starts next, once the current queue has landed
  (hostname-matched crons, the quoted-glob fix, provision Phases 1–2).
- Built per the Fable rulings and merged to main in b1d6397f4; dogfood run
  and closure in ab46984cf.
