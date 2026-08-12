# Plan 00218: plan index row length fast loop

**Status**: Complete
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

`tests/integration/test_plan_index_navigability.py::test_no_index_row_is_a_paragraph`
caps every line of `CLAUDE/Plan/README.md` at 500 characters. That was the only
place the rule existed, so the sole feedback path was a full pytest run — long
after the commit that introduced the offender. The rule was breached twice in
one session before anyone noticed.

This is a DBF gap (`CLAUDE.md` Core Standard 15), and it is the *inverse* of the
usual one: the batch guard exists and the fast guard is missing. `plan_qa` runs
at Write/Edit time, at `git commit`, and at SessionStart, and its catalogue has
no row-length rule — so the one plan document with a shape rule had no
fast-loop enforcement at all.

The fix adds `index-row-length` to the `plan_qa` catalogue on all three
surfaces, reading the SAME constant the integration test reads. The test stays
as the batch equivalent; this plan adds the fast equivalent, it does not
replace anything.

## Goals

- Add `index-row-length` to the `plan_qa` check catalogue at EDIT, COMMIT and SWEEP.
- Give the 500-character limit exactly ONE definition, imported by both the new
  check and the existing integration test.
- Keep `test_no_index_row_is_a_paragraph` passing, unmodified in behaviour.
- Match the existing test's definition of an offending line exactly, so the fast
  and batch guards can never disagree about what is a violation.

## Non-Goals

- No change to the index's total-size ceiling (`MAX_BYTES`), which has no
  fast-loop equivalent and is out of scope here.
- No config knob for the limit. The batch test asserts a fixed 500; a
  configurable rule could be set to 800 while the test still failed at 500,
  which reintroduces exactly the drift this plan removes.
- No relaxation of `plan-doc-size`'s index exemption. The index is correctly
  exempt from the per-plan size tiers; this is a separate rule, not a special
  case bolted onto those.

## Context & Background

Measured before building anything (see JOURNAL for the raw figures):

- catalogue is 35 registered specs / 30 distinct check ids; none covers line length
- current index: 1,176 lines, 100,732 bytes, **0 lines over 500** (longest 485)
- `plan-doc-size` is registered at **EDIT only** — there is no commit-stage
  size check, so the "sibling concern is enforced at both edit and commit"
  premise this plan started from was wrong and is not relied on
- live modes: `edit_mode: block`, `commit_gate_mode: warn`, `sweep_mode: advise`

The mode overrides the declared `Level`. So under current config this rule
DENIES at edit time and ADVISES at commit time. It is not honest to describe
it as "blocking over-long rows" generally — the accurate claim is that it
collapses the feedback loop from a full-suite run to the moment of the write.

## Tasks

### Phase 1: Single definition of the limit

- [x] ✅ **Task 1.1**: Move the 500 limit into `plan_qa/types.py` as
  `DEFAULT_INDEX_ROW_MAX_CHARS`, and have the integration test import it
  instead of declaring its own literal.

### Phase 2: The check (TDD)

- [x] ✅ **Task 2.1**: Failing unit tests for `index-row-length` — scope,
  worsening/steady/shrinking edit tiers, and COMMIT/SWEEP whole-file behaviour.
- [x] ✅ **Task 2.2**: Implement `plan_qa/checks/index_row_length.py` and
  register it at EDIT, COMMIT and SWEEP.
- [x] ✅ **Task 2.3**: Give `ReadmeIndex` the source lines the COMMIT/SWEEP
  stages need, so the check reads parsed state rather than re-reading the file.

### Phase 3: Wire the edit surface

- [x] ✅ **Task 3.1**: Failing handler test — `PlanQaEditHandler` must match a
  Write/Edit of the plan-index `README.md`.
- [x] ✅ **Task 3.2**: Extend `_is_lintable_plan_file` to the plan index and
  update the handler's `get_claude_md()`, `plan_qa_commit_gate`'s invariant
  list, `HANDLER_REFERENCE.md` and `PlanWorkflow.md`.

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Confirm the new rule flags 0 lines on the current index.
- [x] ✅ **Task 4.2**: Confirm `test_no_index_row_is_a_paragraph` still passes.
- [x] ✅ **Task 4.3**: Run `./scripts/qa/llm_qa.py all`.
- [x] ✅ **Task 4.4**: Daemon restart verification — deferred to the coordinator
  after merge. A worktree has no daemon of its own, and restarting the dogfood
  daemon from here would disturb the live session that owns it. Discharged on
  merge: daemon restarted RUNNING with no load errors, and `plan-qa --sweep`
  exercised the new check against the real index, reporting 0 row-length
  findings alongside the two pre-existing staleness advisories.

## Technical Decisions

### Decision 1: All three surfaces, and why EDIT is the load-bearing one

**Context**: The brief flagged the edit surface as possibly disproportionate,
since `plan_qa_edit` lints `PLAN.md` and the index is a `README.md`.

**Decision**: Wire all three. EDIT is not optional here — it is the only
surface whose live mode (`edit_mode: block`) matches the strictness of the
existing test, which FAILS the suite. Wiring only the commit gate would leave
the fast loop strictly weaker than the status quo it is meant to shorten.

The extension is also smaller than it looks: the shared classifier already
models `PlanFileKind.PLAN_INDEX`, and every other EDIT check scopes itself
through `edit_target()`, which returns `None` for anything that is not a
`PLAN.md`. So widening the handler gate cannot make a sibling check misfire on
a README.

COMMIT and SWEEP carry the DBF corollary: a write-time guard does not see what
is already on disk. An over-long row can arrive by merge, by script, or from a
sibling worktree, and only the batch surfaces catch those.

### Decision 2: Measure every line, not only parsed rows

**Context**: `ReadmeIndex` already parses rows, so a row-scoped rule was
available and looks more precise.

**Decision**: Measure every line, exactly as the integration test does. Two
guards over one constant must also share one definition of a violation, or the
constant is single-sourced while the rule silently is not. A 900-character
prose paragraph in an index is the same navigability failure as a 900-character
row, so the broader definition is also the correct one on its merits.

### Decision 3: Only a worsening edit blocks

**Context**: `plan-doc-size` never denies an edit that shrinks or holds an
already-oversized file, so an over-limit document can always be refactored down.

**Decision**: Same tiering, on the axis that matters here — the check compares
over-limit lines before and after. More of them, or a longer worst offender,
is worsening and blocks; fewer or unchanged never blocks. An index that somehow
acquired a long row stays editable, including by the edit that fixes it.

## Success Criteria

- [x] `index-row-length` registered at EDIT, COMMIT and SWEEP
- [x] Exactly one definition of 500 in the codebase, imported by the test
- [x] `test_no_index_row_is_a_paragraph` passes unchanged in behaviour
- [x] The rule flags 0 lines on the current index (matching the test)
- [x] QA green apart from the two worktree-shaped checks (see JOURNAL)
- [x] Daemon restart verified after merge (coordinator-owned)

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00218-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- delivery commit hash -->
