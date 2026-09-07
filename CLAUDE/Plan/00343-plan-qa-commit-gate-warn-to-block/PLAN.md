# Plan 00343: flip the plan QA commit gate from warn to block

**Status**: Not Started
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Single agent

## Overview

`plan_workflow.qa.commit_gate_mode` has been `warn` since the plan QA commit
gate shipped, and the config comment states the intent plainly: "warn-first
rollout; flip to block after clean dogfooding". Nothing has decided whether
that dogfooding is now clean, so the flip has simply never been revisited.

In `warn` mode `PlanQaCommitGateHandler` renders EVERY finding as advisory
regardless of level — only `_MODE_BLOCK` converts a `Level.BLOCK` finding into
a DENY. So the gate's entire BLOCK tier is currently decorative, and adding
more BLOCK-level checks does not change that.

That is not hypothetical. **Plan 00341 was filed because an advisory fired on
commit `923fd583` and the plan stayed `Not Started` for five days anyway** —
an advisory is a suggestion an agent mid-commit is free to scroll past, and one
did. 00341 shipped a correct BLOCK-level finding and then had to record that
BLOCK-level is not the same as blocking. This plan is the lever it deliberately
did not pull, because flipping the mode changes the behaviour of EVERY plan QA
commit check at once and that is a project-wide decision, not a side effect of
one check.

## Goals

- Decide, with measured evidence rather than argument, whether
  `commit_gate_mode: block` is safe for this repository today.
- If it is, flip it and record what the first blocked commit looked like.
- If it is not, name precisely which checks are not ready and why, so the
  question is answerable next time rather than re-opened from scratch.

## Non-Goals

- Changing any individual check's level. Which findings are BLOCK is each
  check's own decision; this plan only decides whether BLOCK means anything.
- Changing `documentation.qa.commit_gate_mode`. The docs QA gate has its own
  warn-first rollout, its own checks and its own false-positive profile — it
  deserves the same treatment but not the same commit.
- Changing `edit_mode` (already `block`) or `sweep_mode` (already `advise`).

## Tasks

### Phase 1: Measure before deciding

- [ ] ⬜ **Task 1.1**: Enumerate every check that can currently emit a
  `Level.BLOCK` finding at `Stage.COMMIT`. That set — not the whole plan QA
  suite — is what the flip actually arms.

- [ ] ⬜ **Task 1.2**: Replay those checks over recent history and count how
  many commits would have been DENIED. Plan 00341 Task 2.1 used a 250-commit
  replay for exactly this purpose and it changed the design rather than
  confirming it, so the technique is proven here. A flip whose first run
  denies a large fraction of ordinary commits is not ready, whatever the
  reasoning says.

- [ ] ⬜ **Task 1.3**: Classify every would-be denial as a true or false
  positive by reading the commit. A single false-positive SHAPE matters more
  than the raw count, because it will recur.

### Phase 2: Flip, or record why not

- [ ] ⬜ **Task 2.1**: If Phase 1 is clean, flip `commit_gate_mode` to `block`
  and restart the daemon. The escape hatch already exists and should be named
  in the commit message: the mode is one config key, so reverting is one edit.

- [ ] ⬜ **Task 2.2**: If Phase 1 is not clean, record which check produced the
  false positives and file the narrowing as its own task. "Not yet, because
  check X fires on shape Y" is a real result; "it felt risky" is not.

- [ ] ⬜ **Task 2.3**: Either way, update the config comment. It currently
  promises a decision that has never been made, which is its own small
  instance of the rot Plan 00341 is about.

## Success Criteria

- [ ] The set of commit-stage BLOCK-capable checks is written down, not
  inferred.
- [ ] The flip decision cites a replay count and a false-positive
  classification, not a judgement call.
- [ ] `commit_gate_mode` and its config comment agree with each other and with
  reality.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00343-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: Plan 00341 Task 3.2, which reached this lever and deliberately left
  it unpulled — see that plan's journal entry "BLOCK-level is not the same as
  blocking".
- Prior art: Plan 00144 introduced the plan QA subsystem and its warn-first
  rollout; Plan 00341 added the first commit-stage BLOCK finding that the flip
  would arm.
