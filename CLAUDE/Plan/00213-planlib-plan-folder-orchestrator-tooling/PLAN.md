# Plan 00213: planlib plan folder orchestrator tooling

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

An upstream proposal arrived from a client project: promote its plan-folder
orchestrator tooling (`planlib`) into the hooks daemon, so that every project
using the plan workflow gets the same bash library rather than each one growing
its own. The proposal is a **generic extraction** of code already running in a
private infrastructure repository — project-specific facts were pulled out into
a configuration seam, and the library is presented complete and self-contained
rather than excerpted.

The proposal arrived verified rather than sketched, which is why it is worth
holding: the library was concatenated and checked with `bash -n` (asserting
empty stderr, because `bash -n` prints a diagnostic and still exits 0 on a
malformed conditional, so the exit code alone is not the signal), passed
`shellcheck -x -S style`, and had every called function cross-referenced against
every defined one. The `§5` skeletons are explicitly marked as templates
containing placeholders, not runnable code.

This plan exists so the proposal is TRACKED rather than lingering in
`untracked/`. Phase 1 (evaluation only) is complete — see Technical Decisions
for the recorded ADAPT recommendation. Phase 2 (adoption) remains gated on a
human scope decision: adopting a ~62KB bash library into the daemon is not
something to begin because the document happens to be well written, or
because an evaluation recommends it.

## Goals

- Preserve the proposal as tracked source with its provenance and verification
  claims intact, so a later evaluation starts from the document rather than from
  a re-derivation.
- Reach an explicit accept / adapt / decline decision on promoting `planlib`
  into the daemon, recorded under Technical Decisions.
- If accepted, land it behind the daemon's existing conventions rather than as a
  foreign body: config-driven seams, the deploy-assets path already used by
  `mkplan.bash`, and QA coverage equal to the rest of the shell surface.

## Non-Goals

- Adopting the library as-is without review. It is a proposal, not a patch.
- Re-verifying the author's claims as a precondition for filing this plan — the
  verification table is recorded as an assertion to be checked at evaluation
  time, not as something this plan takes on trust or on faith.
- Any change to `mkplan.bash` or the plan workflow before a decision is made.

## Context & Background

Supporting documents in this folder (the EXTRACT remedy from Plan 00211 —
durable detail belongs in named files, not inflating PLAN.md):

- `PROPOSAL.md` — the current proposal (v2), self-contained and verified.
- `PROPOSAL-v1-SUPERSEDED.md` — the earlier draft, kept because the daemon's
  own convention is to preserve superseded versions rather than delete them.

## Tasks

### Phase 1: Evaluation

- [x] ✅ **Task 1.1**: Read `PROPOSAL.md` and independently re-run its stated
  verification (`bash -n` with an empty-stderr assertion, `shellcheck -x -S style`, defined-vs-called function cross-reference). Confirmed all three claims exactly as stated — see `EVALUATION.md` §1.
- [x] ✅ **Task 1.2**: Assess overlap with what the daemon already ships —
  `mkplan.bash`, `deploy-plan-workflow`, the `plan_qa` check catalogue — and
  identify what `planlib` adds beyond them. Overlap is minimal; different lifecycle stage — see `EVALUATION.md` §2.
- [x] ✅ **Task 1.3**: Record an accept / adapt / decline decision with rationale
  under Technical Decisions. Recorded: ADAPT.

### Phase 2: Adoption (only if Task 1.3 accepts)

- [ ] ⬜ **Task 2.1**: Define the configuration seam in `.claude/hooks-daemon.yaml`
  and its schema validation
- [ ] ⬜ **Task 2.2**: Wire deployment through the existing idempotent
  plan-workflow asset deploy path
- [ ] ⬜ **Task 2.3**: Bring shell QA coverage up to the standard the rest of the
  shell surface is held to (`shell_audit`, `shellcheck`)
- [ ] ⬜ **Task 2.4**: Stage `config-changes` and `truth-changes` manifests so the
  feature does not ship dormant and undocumented

## Dependencies

- Related: Plan 00211 (plan-size guidance / supporting-docs concept) — this plan
  folder is itself an application of that plan's EXTRACT remedy.

## Technical Decisions

### Decision 1: planlib — ADAPT, not full accept, not decline

**Context**: Phase 1 independently re-ran the proposal's stated verification
and assessed overlap with existing daemon tooling. Full detail (verification
transcripts, per-artefact overlap table, architectural analysis) is in
`EVALUATION.md`; this records the decision and the load-bearing reasons.

**Verification (Task 1.1)**: all three of the proposal's stated claims about
`_planlib.inc.bash` (§3) were independently reproduced and confirmed exactly
as stated — `bash -n` with empty stdout/stderr, `shellcheck -x -S style`
clean (stricter than the daemon's own shell QA gate requires), and a
zero-dangling-reference cross-check across all 24 `plan_*`/`_plan_*`
functions. A bonus dynamic smoke test (not claimed by the proposal, done for
extra confidence) confirmed the pure/testable primitives behave as documented,
including the specific incident-class fix in §1.1 (script-relative,
boundary-bounded root resolution correctly refuses to walk past a nested
repo). However, of the proposal's three named artefacts
(`_planlib.inc.bash`, `plan_script_qa`, `test-planlib.bash`), **only the
library is delivered as complete, runnable code** — the QA handler is a
rules table plus two illustrative snippets, and the test suite is four
stated principles with no runnable file. The proposal itself scopes its
verification table to the library only, but a skim can read it as covering
"the proposal."

**Overlap (Task 1.2)**: minimal, and mostly additive rather than duplicative.
`mkplan.bash`, `deploy-plan-workflow`, and all 30 `plan_qa` checks across its
3 enforcement surfaces operate at plan **creation** and `PLAN.md` **hygiene**
— none inspect executable content. `planlib` addresses a different lifecycle
stage entirely: safe **execution** of operator-run scripts filed inside a
plan folder. The one real new-capability claim (`plan_script_qa` linting
script structural safety) holds up — the daemon has nothing like it today.
The honest answer to "does most of this already exist here" is **no**.

**Options considered**:

1. **Decline** — reject the proposal outright. Rejected: the verified library
   solves a real, previously-encountered incident class with primitives that
   are easy to get subtly wrong if reinvented (named-pipe-vs-`>()` drain
   determinism, the `BASH_SUBSHELL` leg guard, TTY-vs-stdin prompt-ordering).
   Declining would discard genuinely solid, independently-verified work.
2. **Full accept** — land all three artefacts as "Phase 2" per the plan's
   original task list. Rejected: only 1 of 3 artefacts is actually finished
   code. Treating the QA handler and test suite as a four-task polish step
   understates the work — this project's TDD discipline has no RED phase to
   start from for either, since neither exists yet as runnable code.
3. **Adapt** (chosen) — accept the library alone, behind config, on the
   existing `deploy_plan_workflow_if_enabled` seam (already reusable,
   already idempotent, already the mechanism this plan's own Goals section
   names); treat `plan_script_qa` + `test-planlib.bash` as a **separate**,
   honestly-scoped follow-up plan rather than folding them into this one.

**Decision**: ADAPT. If a human authorises Phase 2, re-scope it to land the
library only, then open a new plan for the QA handler and test suite once a
human has also weighed the open architectural question below — this decision
does not resolve it, only surfaces it.

**Open question for the human, not resolved here**: `planlib` is explicitly
operator-invoked (§9 of the proposal) with zero runtime coupling to Claude
Code hook events or anything the daemon governs — unlike `mkplan.bash`, which
manipulates daemon-owned state (the plan counter, `PLAN.md` shape). Whether a
general-purpose, plan-system-agnostic bash safety library belongs inside a
**Claude Code hooks daemon**, versus being a separate vendored library the
daemon merely helps distribute, is a scope call this plan's own Non-Goals
section already reserves for a human.

**Date**: 2026-08-12

## Success Criteria

- [ ] An explicit, recorded decision exists on whether `planlib` is adopted
- [ ] No proposal document remains in `untracked/`
- [ ] If adopted: QA passes, the daemon restarts cleanly, and the feature ships
  with upgrade manifests rather than silently

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00213-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Proposal filed out of `untracked/` and into tracked source at plan creation
