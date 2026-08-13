# Plan 00234: handler value audit

**Status**: In Progress
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Fable (judgement) with Sonnet research agents
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00233 removed `transcript_archiver`. It had been in the tree since the
initial commit, copying every session transcript before every compaction, and it
protected nothing: nothing ever read a copy, and the durability it claimed was
already provided by the original file on the same physical disk. It cost 422 MB
and nobody noticed for the project's entire life.

One instance is an anecdote. The question this plan answers is whether it is a
pattern: across roughly 100 handlers in 16 event types, which others are
producing artefacts nobody reads, guarding conditions that can never occur,
duplicating a check something else already does, or charging more in context
tokens than the advice is worth?

This is an **audit and planning** exercise. It produces evidence and a
prioritised proposal. It does not remove anything — each removal that survives
judgement becomes its own scoped follow-up, so that a removal is never bundled
with the reasoning that justified it.

## Goals

- A per-handler evidence dossier covering every handler in the tree
- A defensible verdict per handler, distinguishing *"never fires"* from
  *"cannot fire"* from *"fires and is not worth it"*
- A prioritised proposal of removals, merges and de-scopings, each with the
  specific evidence that supports it
- A fix for the instrument that should have caught this class and did not

## Non-Goals

- **No code changes in this plan.** Audit and plan only.
- Not a rewrite of handlers judged worth keeping — behaviour changes are
  separate work.
- Not a re-litigation of Plan 00233; that removal is delivered and closed.

## Context & Background

### The shapes worth looking for

Derived from the 00233 post-mortem and the Plan 00196/00230 vacuous-guard
lessons. A handler is suspect when it shows one of these:

| Shape                  | Test                                                                                                         |
| ---------------------- | ------------------------------------------------------------------------------------------------------------ |
| **No consumer**        | It writes an artefact — file, log, cache, sidecar — that nothing in the repo reads. The 00233 shape exactly. |
| **Vacuous guard**      | Its condition cannot be true for realistic input. Registered, running, blind — indistinguishable from clean. |
| **Duplicated**         | Another handler, a QA script, a linter, or Claude Code itself already enforces it.                           |
| **Cost exceeds value** | An advisory that fires often, injecting context tokens for advice CLAUDE.md already carries.                 |
| **Never justified**    | Introduced with no stated need, and no evidence since that it has ever helped.                               |

### The trap in this audit

The daemon's own `hooks-daemon verdicts` report prints a **"Never-fired
handlers"** list, and it is tempting to read that as the answer. It is not. The
list is drawn from a rolling sample that currently retains **65 minutes**, and it
names handlers such as `prevent-destructive-git` whose entire value is that they
fire rarely and catastrophically. Rarity is what success looks like for a safety
handler.

"Never fires" is therefore not evidence of pointlessness. Only "**cannot** fire",
established from the code and its tests, is — and that is what the dossiers are
for. See `RESEARCH-verdict-log-is-blind.md`.

## Tasks

### Phase 1: Evidence gathering (parallel, read-only)

- [x] ✅ **Task 1.1**: Split ~100 handlers into seven cohorts and dispatch one
  Sonnet research agent per cohort against a shared evidence rubric
- [x] ✅ **Task 1.2**: Measure the live verdict log directly — the one input no
  cohort agent can obtain — and record the anti-inference warning above
- [ ] ⬜ **Task 1.3**: Collect all seven cohort dossiers into this plan folder

### Phase 2: Judgement

- [ ] ⬜ **Task 2.1**: Fable reads every dossier plus the verdict-log evidence
  and assigns a verdict per handler, with the evidence that carries it
- [ ] ⬜ **Task 2.2**: Separate the verdicts into removals, merges, de-scopings
  and keeps — a merge into an existing check is a better outcome than a deletion
  wherever the duty is still wanted
- [ ] ⬜ **Task 2.3**: Rank by confidence and by blast radius, so the safest and
  clearest removals can go first

### Phase 3: Defence before fix

- [ ] ⬜ **Task 3.1**: For each confirmed finding, name the guard that should
  have caught it and did not — the defect is the blindness, not the instance
- [ ] ⬜ **Task 3.2**: Propose the instrument fix that would make this class
  visible continuously rather than by audit

### Phase 4: Proposal

- [ ] ⬜ **Task 4.1**: Write the prioritised proposal into this plan
- [ ] ⬜ **Task 4.2**: Hand to the human for scope decisions before any removal
  work is scheduled

## Success Criteria

- [ ] Every handler in the tree carries a recorded verdict — including the
  keeps, so the next audit starts from a baseline rather than from scratch
- [ ] Every removal proposal cites specific evidence, not a firing count
- [ ] No handler is proposed for removal on "never fired" evidence alone
- [ ] The instrument gap is identified and a fix proposed
- [ ] Zero code changes in this plan

## Risks & Mitigations

| Risk                                                      | Impact | Probability | Mitigation                                                                          |
| --------------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------------- |
| "Never fired" misread as "pointless", deleting safety net | High   | High        | Explicit anti-inference warning in the evidence note and in every agent brief       |
| Research agents manufacture suspicion to seem thorough    | Medium | Medium      | Briefs instruct one-line KEEP verdicts; a separate judge weighs, researchers do not |
| Audit becomes a rewrite                                   | Medium | Medium      | Non-goal stated; removals land as separate scoped follow-ups                        |
| Agents collide on the shared git index                    | Medium | Low         | Agents are read-only bar one dossier file each; no git mutation permitted           |

## Delivery & Milestones

- Seven cohort research agents dispatched; verdict-log evidence note landed
