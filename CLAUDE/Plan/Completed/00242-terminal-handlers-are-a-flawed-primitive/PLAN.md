# Plan 00242: Terminal Handlers Are a Flawed Primitive

**Status**: Complete
**Created**: 2026-08-14
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00241 fixed four handlers that were terminal while carrying an advisory
path, so their ALLOW ended the chain and silently disabled every
higher-priority-number handler. The guard added there covers handlers with a
configurable warn mode — which is where the damage was concentrated, but it
is a narrow rule over a structural problem.

The structural problem: **the chain already implements exactly the merge
semantics that would make `terminal` unnecessary, and `terminal` overrides
them.** `core/chain.py` keeps the most restrictive decision seen, so a later
advisory ALLOW cannot wash out an earlier deny; and `accumulated_context`
already collects advisory output from every non-terminal handler. Where the
two mechanisms disagree, `terminal` wins and the merge never runs. That is
why the defect was invisible: nothing was broken about the merge.

The proposal is to make terminality a property of the DECISION rather than of
the handler, and to return one merged response per event.

## Goals

- Remove the class of defect where a handler silently disables its successors
- Report EVERY violation of a single tool call at once, not one per round trip
- Keep `terminal` only where it cannot change semantics, or delete it

## Non-Goals

- Changing what any individual handler decides
- Re-litigating Plan 00241's fixes; this generalises them

## Context & Background

The shape to preserve: a DENY may short-circuit safely, because
most-restrictive-wins means nothing later can un-deny it. An ALLOW may never
short-circuit — "I allow this, therefore nobody else may look" is not a
coherent claim.

Against short-circuiting even on deny: a write violating three rules
currently costs three round trips (fix, retry, hit the next). One merged
response naming all three is a real improvement, and is the reason to prefer
collecting over stopping.

## Tasks

### Phase 1: Establish the ground truth

- [x] ✅ **Task 1.1**: Enumerate every terminal handler and classify it —
  `TERMINAL-HANDLERS.md`
  - [x] ✅ Terminal-and-only-ever-denies (safe today, no semantic change)
  - [x] ✅ Terminal-with-a-reachable-ALLOW (the defect class)
  - [x] ✅ Terminal-ALLOW-as-the-point (`auto_approve_reads` on
    PermissionRequest, where "approve and stop" IS the semantic) — so the
    rule must be per-event, not global (`allow_is_final`, `ab3cab93`)
- [x] ✅ **Task 1.2**: Measure the cost of running every matching handler —
  `MEASUREMENTS.md`
  - [x] ✅ Several handlers shell out to git; today a terminal deny at
    priority 10 skips them, so running everything makes the BLOCKED path the
    slowest path — measured: worst case 2.03 ms p50 vs 0.34 ms
  - [x] ✅ Decide from data, not intuition — a deny does not short-circuit in
    collect-all mode

### Phase 2: Side effects

- [x] ✅ **Task 2.1**: Audit handlers with side effects — `SIDE-EFFECTS.md`
  - [x] ✅ Rate limiters and state writers (`command_hints` TTLs,
    `recovery_cron_advisor` intervals, `lsp_enforcement` block-once) would
    now fire on events that end up DENIED — burning a cooldown for a tool
    call that never ran (`e85bdabc`, `6dd48264`)
  - [x] ✅ Decide whether side effects move to a post-decision phase —
    committed or rolled back after the decision via
    `Handler.commit_side_effects` + `SideEffectJournal` (`ab3cab93`)

### Phase 3: The merged response

- [x] ✅ **Task 3.1**: Any deny is a deny; collect ALL denies (`ab3cab93`,
  behind `daemon.chain.collect_all_violations`, `6dd48264`)
- [x] ✅ **Task 3.2**: Collect all advisories into one table (`ab3cab93`)
- [x] ✅ **Task 3.3**: Settle attribution — with three denies, which owns the
  `To disable:` footer? `decided_by` already answers this (first restrictive
  wins); make that deliberate rather than incidental — first restrictive owns
  reason AND footer (`ab3cab93`)
- [x] ✅ **Task 3.4**: Keep the response within whatever size is sane; three
  full deny reasons concatenated may need summarising — bounds recorded in
  `MEASUREMENTS.md` (`ab3cab93`)

### Phase 4: Retire the flag

- [x] ✅ **Task 4.1**: Reduce `terminal` to an optimisation that cannot change
  semantics, or delete it — kept as a blocked-path optimisation; rationale in
  `TERMINAL-HANDLERS.md` (`ab3cab93`)
- [x] ✅ **Task 4.2**: Replace Plan 00241's narrow warn-mode guard with the
  general invariant once it holds (`d613e972`, `ab3cab93`)
- [x] ✅ **Task 4.3**: Update `CLAUDE.md`'s "Terminal vs Non-Terminal" section
  and `HANDLER_DEVELOPMENT.md` (`ab8ee7e3`)

## Dependencies

- Related: Plan 00241 (fixed the four instances; this generalises)
- Related: Plan 00237 (shadowed handlers that had never run in any release)

## Success Criteria

- [x] No handler can silently disable another (`ab3cab93`)
- [x] A tool call violating several rules reports all of them at once
  (`daemon.chain.collect_all_violations`, `6dd48264`)
- [x] The cost of the change is measured, not assumed (`MEASUREMENTS.md`)
- [x] Side-effecting handlers do not fire for denied tool calls
  (`e85bdabc`, `6dd48264`)
- [x] Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/30-an-allow-never-ends-the-chain.md` (the
  callout) and the `daemon.chain.collect_all_violations` entry in
  `UNRELEASED/config-changes/v3.63.0.yaml` (`ab8ee7e3`, `6dd48264`)

## Risks & Mitigations

| Risk                                                 | Impact | Probability | Mitigation                                                   |
| ---------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------ |
| Running every handler makes the blocked path slowest | Medium | High        | Measure in Phase 1; a deny may still short-circuit if needed |
| Side effects fire for tool calls that never ran      | Medium | High        | Phase 2 audits them before any dispatch change               |
| A merged deny response becomes unreadably long       | Medium | Medium      | Task 3.4; lead with the highest-priority deny                |
| Behaviour change surprises existing projects         | High   | Medium      | Ship behind a config flag first, default off, then flip      |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. -->

- Raised while reviewing the Plan 00241 fixes: the guard is narrow, the
  underlying primitive is the problem
- Invariant, collect-all merge and post-decision commit: `ab3cab93` (guard
  deletion `d613e972`)
- Config surface and per-handler history: `6dd48264`
- Rate limiters journalled: `e85bdabc`
- Documentation and release-notes callout: `ab8ee7e3`
