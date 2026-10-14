# Plan 00524: foreground blocking wait goes to the background

**Status**: Not Started
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #117

## Overview

An agent sometimes runs a Bash call whose only job is to wait, in the
foreground with a long tool timeout. Examples are an `until grep -q …; do sleep 10; done` loop, a `timeout 590 bash -c '…'` wrapper around one, a long
bare `sleep`, or a foreground `tail -f`. While such a call runs, the human
cannot message the agent without rejecting the call. A call started with
`run_in_background: true` notifies the agent when it ends, and the Monitor
tool streams output, so a foreground wait gains nothing.

No rule catches this today. `R-UNBOUNDED-LIVENESS-LOOP`
(`self_matching_process_probe`, Plan 00363's handler family) deliberately
exempts capped loops and log-marker loops. Its own fix text recommends
exactly these shapes ("Wrap it in `timeout 3600 bash -c '…'` … or wait on a
log marker") without saying to run them in the background. That advice is a
defect in its own right, independent of any new rule.

A new deny is a new safety control, so the issue-sdlc runbook routes it to
the owner. Phase 1 is safe either way and can go ahead once the owner agrees.

## Owner decision needed

1. Deny or advise? Should a foreground wait be **denied**, with the deny
   naming `run_in_background: true` and Monitor, or only **advised**?
2. Thresholds: a short deliberate pause (e.g. `sleep 2`) must stay allowed.
   Proposed: a bare `sleep` above 30 seconds, any sleep-only-body `until` or
   `while` loop, and a foreground `tail -f` or `inotifywait`. Accept, or name
   others?

## Goals

- The existing rule's fix text never recommends a foreground wait.
- With the owner's ruling, a foreground pure-wait call is steered to the
  background or to Monitor, and a short pause or a loop doing real work is
  untouched.

## Non-Goals

- Changing `R-WAIT-ON-WRAPPER-PID` or `R-PGREP-SELF-MATCH`, which cover waits
  that end at the wrong time.
- Judging any call already started with `run_in_background: true`.

## Tasks

### Phase 1: Fix the advice (no new rule)

- [ ] ⬜ **Task 1.1**: `R-UNBOUNDED-LIVENESS-LOOP`'s deny, its guidance and its
  rule summary say to start the capped or log-marker wait with
  `run_in_background: true`, or to use Monitor. Tests assert the new text.

### Phase 2: The new rule (after the owner's ruling)

- [ ] ⬜ **Task 2.1**: RED: tests for each wait shape in the foreground
  (judged), the same shape with `run_in_background: true` (allowed), `sleep 2`
  (allowed), and a loop whose body does real work (allowed).
- [ ] ⬜ **Task 2.2**: GREEN: the rule, in the deny or advise mode the owner
  chose, inside the `self_matching_process_probe` handler family. Update its
  guidance and add a release note.

## Success Criteria

- [ ] No rule's fix text recommends a foreground blocking wait, proven by test.
- [ ] Every wait shape the owner accepted is judged in the foreground and
  allowed in the background, proven by tests that failed first.
- [ ] Release-bound consequences recorded in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00524-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by the issue-sdlc loop from #117; the dedupe scout found no live
  overlap (prior art: Plan 00363).
