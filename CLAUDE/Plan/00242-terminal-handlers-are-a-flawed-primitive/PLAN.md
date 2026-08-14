# Plan 00242: Terminal Handlers Are a Flawed Primitive

**Status**: Not Started
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

- [ ] ⬜ **Task 1.1**: Enumerate every terminal handler and classify it
  - [ ] ⬜ Terminal-and-only-ever-denies (safe today, no semantic change)
  - [ ] ⬜ Terminal-with-a-reachable-ALLOW (the defect class)
  - [ ] ⬜ Terminal-ALLOW-as-the-point (`auto_approve_reads` on
    PermissionRequest, where "approve and stop" IS the semantic) — so the
    rule must be per-event, not global
- [ ] ⬜ **Task 1.2**: Measure the cost of running every matching handler
  - [ ] ⬜ Several handlers shell out to git; today a terminal deny at
    priority 10 skips them, so running everything makes the BLOCKED path the
    slowest path
  - [ ] ⬜ Decide from data, not intuition

### Phase 2: Side effects

- [ ] ⬜ **Task 2.1**: Audit handlers with side effects
  - [ ] ⬜ Rate limiters and state writers (`command_hints` TTLs,
    `recovery_cron_advisor` intervals, `lsp_enforcement` block-once) would
    now fire on events that end up DENIED — burning a cooldown for a tool
    call that never ran
  - [ ] ⬜ Decide whether side effects move to a post-decision phase

### Phase 3: The merged response

- [ ] ⬜ **Task 3.1**: Any deny is a deny; collect ALL denies
- [ ] ⬜ **Task 3.2**: Collect all advisories into one table
- [ ] ⬜ **Task 3.3**: Settle attribution — with three denies, which owns the
  `To disable:` footer? `decided_by` already answers this (first restrictive
  wins); make that deliberate rather than incidental
- [ ] ⬜ **Task 3.4**: Keep the response within whatever size is sane; three
  full deny reasons concatenated may need summarising

### Phase 4: Retire the flag

- [ ] ⬜ **Task 4.1**: Reduce `terminal` to an optimisation that cannot change
  semantics, or delete it
- [ ] ⬜ **Task 4.2**: Replace Plan 00241's narrow warn-mode guard with the
  general invariant once it holds
- [ ] ⬜ **Task 4.3**: Update `CLAUDE.md`'s "Terminal vs Non-Terminal" section
  and `HANDLER_DEVELOPMENT.md`

## Dependencies

- Related: Plan 00241 (fixed the four instances; this generalises)
- Related: Plan 00237 (shadowed handlers that had never run in any release)

## Success Criteria

- [ ] No handler can silently disable another
- [ ] A tool call violating several rules reports all of them at once
- [ ] The cost of the change is measured, not assumed
- [ ] Side-effecting handlers do not fire for denied tool calls

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
