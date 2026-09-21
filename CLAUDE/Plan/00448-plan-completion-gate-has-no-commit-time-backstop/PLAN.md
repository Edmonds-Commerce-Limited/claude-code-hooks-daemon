# Plan 00448: plan completion gate has no commit time backstop

**Status**: Not Started
**Created**: 2026-09-21
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`plan_done_requires_holding_area` (project handler, PreToolUse, priority 51,
terminal) denies a flip to `Complete` whose Success Criteria name neither a
holding-area artefact nor an explicit "no release-bound consequences: <why>".
It keys on `Write` and `Edit`. A `PLAN.md` written through Bash — a heredoc,
`>`, `>>`, `tee` — never reaches it, and there is no commit-time check that
would catch the same state a moment later.

**This is not hypothetical and it is not a logic defect.** Plan 00437 reached
`Complete`, was archived, and sat in the v3.66.0 holding window with neither
spelling present; it was found by reconciling the 23 plans completed since
v3.65.0 against the 20 release notes on hand. The handler's own `matches()`
was then run against that plan's exact file content and returned `True` — it
would have blocked that flip. So the rule is right and the route around it is
the whole finding.

The remedy pattern already exists in this repository and was built for exactly
this reason. `sensitive_content` has a write-time check AND a `git commit`
check over the staged diff, because a Bash write reaches disk unexamined and
the commit is the next moment at which the state and the guard are both in
reach. Plan 00252 built that backstop; Plan 00202 established the dual-layer
shape; Plan 00260 measured the side-door across 22 handlers that key on tool
names. This plan applies that settled pattern to one more gate.

**The class is worth naming, because this gate is not special.** Any handler
that judges file CONTENT on `Write`/`Edit` has the same hole. The question
this plan should answer alongside the fix is whether the project wants a
commit-time twin for every such gate, or case by case for the ones whose
escape has a lasting consequence — a plan that ships wrong is durable, a
scratch note is not.

## Goals

- A `PLAN.md` at `Complete` without a holding-area statement cannot reach a
  commit, whichever tool wrote it.
- The commit-time check and the write-time check agree by construction, not by
  two copies of a regex drifting apart.
- Plan 00437's escape is the regression fixture: the check must observe RED
  against that content and GREEN after.

## Non-Goals

- **No change to the rule itself.** The two accepted spellings, the priority,
  the active-plan-root scoping and the archived-plan exemption all stay as they
  are. This plan adds a route, not a judgement.
- **No audit of every Write/Edit-keyed handler.** The class question is raised
  in the Overview and should be recorded, not answered by building twelve
  backstops in one plan.
- **No retroactive sweep of archived plans.** Archived plans are history; 00437
  was corrected in place as a deliberate one-off and that is recorded in its
  Success Criteria.

## Tasks

### Phase 1: the backstop

- [ ] ⬜ **Task 1.1**: RED — a test staging a `PLAN.md` at `Complete` whose
  Success Criteria carry neither spelling, asserting the commit is denied. Use
  Plan 00437's pre-correction content as the fixture. It must fail today.

- [ ] ⬜ **Task 1.2**: GREEN — the commit-time check, sharing the status
  parsing and the criterion regex with the write-time handler rather than
  restating them.

- [ ] ⬜ **Task 1.3**: Confirm the write-time handler's behaviour is unchanged
  — its existing tests and its acceptance probes pass untouched.

### Phase 2: the class

- [ ] ⬜ **Task 2.1**: Record the general finding where the next handler author
  will meet it: a content guard keyed on `Write`/`Edit` is a floor, not a
  ceiling, and the commit is where the missing half goes. Name 00252/00202 as
  the pattern and 00437 as the cost.

## Success Criteria

- [ ] The RED test observed failing before the change and passing after.
- [ ] A `Complete` flip written by a Bash heredoc is denied at commit time.
- [ ] No second copy of the status parsing or the criterion regex exists.
- [ ] `llm_qa.py all` passes — read the `QA: N/35 PASSED` line and the per-gate
  markers, not the wrapper exit code, which has returned 0 over failing
  gates in this project before.
- [ ] Release-bound consequence recorded in the holding area, or an explicit
  statement that there is none.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00448-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
