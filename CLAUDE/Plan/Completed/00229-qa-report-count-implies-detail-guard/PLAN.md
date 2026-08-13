# Plan 00229: qa report count implies detail guard

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (TDD)

## Overview

Plan 00226 fixed a QA report that said `N failed` and then named nothing. The
producer (`run_tests.sh`) and the consumer (`llm_qa.py`) disagreed about one
token, so the failing-test names silently vanished and an agent had to re-run
the suite to find out what broke — during Plan 00224 that cost a real failure
which was never identified, because the re-run did not reproduce it.

That fix was per-report, and Plan 00226 named this follow-up itself: the same
shape can occur in any of the twenty reports, and nothing asks the general
question. This is the Core Standard 15 second half — the instance was fixed,
the guard that would have caught it was not built.

The guard is unusually well-founded here because the promise is already
written down. Every entry in `TOOL_REGISTRY` carries a `jq_hint` that is
PRINTED TO THE OPERATOR under the summary line:

```
✅ magic_values: 0 violations
   magic_values.json | jq '.violations[] | {file, line, rule, message}'
```

So the tool tells the operator exactly where the detail lives. If the summary
reports a non-zero count and that hint yields nothing, the tool has lied — and
nothing currently notices. The guard's job is to verify the promise the tool
already makes, which keeps the hint as the single source of truth rather than
introducing a second table of detail-array keys to drift against it.

## The gap this reopens

`tests` is the one report whose `jq_hint` is `jq '.summary'` — it points at the
COUNT, not at a detail array. That is not a footnote; it is why Plan 00226's
defect was invisible for so long. A reader following the printed hint is sent
back to the number they already had, so the missing `.tests[]` detail had no
surface that could look wrong.

Any guard built here must therefore check the ARRAY THE SUMMARIZER ACTUALLY
READS, not only the array the hint names, or it will reproduce exactly the
blind spot it exists to close.

## Goals

- A guard asserting, for every report in `TOOL_REGISTRY`, that a non-zero
  failure/violation count implies operator-reachable detail
- The `tests` hint gap closed, or recorded as a deliberate exemption with a
  reason
- The guard derives its per-report knowledge from existing declarations rather
  than a hand-maintained parallel list

## Non-Goals

- Changing what any QA tool CHECKS. This is about reporting fidelity only
- Rendering every report's detail inline. Nineteen reports deliberately
  delegate to the `jq` hint to keep the artifact small; that design stands, and
  the guard is about the detail being REACHABLE, not inline
- Re-auditing Plan 00226's `tests` fix, which has its own regression tests

## Context & Background

The separator that makes this worth a guard rather than a one-line fix is the
cost of a miss. A QA report that under-reports does not fail loudly — it
produces a green-looking artifact with a number and no names, and the agent
reading it cannot tell the difference between "no detail exists" and "the
detail was dropped". That is the same silent-void class as Plan 00222/00225/
00227/00228, in the reporting layer rather than the matching layer.

The verification failure that produced Plan 00228's late surprise is also
relevant: a selection chosen by "files I edited" missed seven tests, because
the change was to a shared helper. A guard that enumerates from the registry
cannot be under-selected the same way.

## Tasks

### Phase 1: Establish the contract

- [x] ✅ **Task 1.1**: Enumerated all twenty. The result is uniform enough to
  state rather than tabulate:

  - **Count key**: `summary.total_violations` for 15 reports;
    `total_errors` (`type_check`), `total_issues` (`security`,
    `dependencies`), `failed` (`tests`), `failed_probes` (`smoke_test`)
  - **Hint's detail array**: `.violations[]` for 15, `.errors[]`, `.issues[]`
    (×2), `.probes[]` — and `.summary` for `tests`, the lone exception
  - **Summariser's detail array**: none for 19 (they render a count only and
    delegate to the hint); `.tests[]` filtered on `outcome == "failed"` for
    `tests`

  So the array a report's detail lives in is derivable from its `jq_hint` by
  reading the leading `.<key>[]` — no parallel table, and a newly added report
  is covered without anyone extending a list. `tests` is the single entry where
  that derivation yields nothing, which is precisely the report whose detail
  went missing in Plan 00226

- [x] ✅ **Task 1.2**: Decided — FIX the `tests` hint rather than exempt it,
  see Decision 1. `jq_hint` is referenced nowhere outside `llm_qa.py` (checked
  via `findReferences`: 20 registry definitions, the field declaration, and one
  render site), so nothing is coupled to its current value

### Phase 2: Build the guard (RED first)

- [x] ✅ **Task 2.1**: `tests/unit/qa/test_llm_qa_count_implies_detail.py`.
  RED first, and it failed on exactly the report Decision 1 predicted:
  2 failed / 46 passed, both failures `tests`
- [x] ✅ **Task 2.2**: Vacuity and teeth — the registry is asserted discovered
  rather than hardcoded, the in-scope set non-empty, every exemption must name
  a real report and state a reason; and `TestTheGuardHasTeeth` asserts the
  count-with-empty-array shape is rejected, a populated one accepted, and a
  `.summary` hint rejected
- [x] ✅ **Task 2.3**: Green across all twenty (56 passed, including Plan
  00226's own regression tests). One test was rewritten before it ever ran
  green: its first draft was `if a != b: return; assert a == b`, which cannot
  fail. It now probes which arrays a summariser actually reads and asserts
  that set is a subset of the array its hint names

### Phase 3: Fix what the guard surfaces

- [x] ✅ **Task 3.1**: One finding, investigated rather than assumed: the
  `tests` hint. Per Decision 1 it was FIXED to
  `jq '.tests[] | select(.outcome == "failed") | .name'` rather than exempted,
  and the entry schema was read from the producer (`run_tests.sh` emits
  `{"name": <nodeid>, "outcome": "failed"}`) instead of guessed. The exemption
  map ships EMPTY, which is the honest outcome here — unlike Plan 00228, no
  surfaced report turned out to be correct-as-is
- [x] ✅ **Task 3.2**: Dogfooded — the rendered line now reads
  `tests.json | jq '.tests[] | select(.outcome == "failed") | .name'` instead
  of sending the reader back to `.summary`. Full QA and daemon restart below

### Phase 4: The render-time half

- [x] ✅ **Task 4.1**: `_detail_is_missing()` in `llm_qa.py` — when a report
  claims failures and the array its hint names is empty, `summarize_tool`
  appends a warning line saying the count has no detail behind it and must not
  be read as "nothing to fix". See Decision 2 for why this cannot be a test
- [x] ✅ **Task 4.2**: `detail_array_key()` and `failure_count()` moved INTO
  `llm_qa.py`, and the guard now binds to those instead of its own copies. The
  first draft reimplemented the hint parse in the test file, which was free to
  drift from the code that runs — the same producer/consumer split this plan
  generalises, reproduced inside its own guard
- [x] ✅ **Task 4.3**: Teeth proven by MUTATION, not assumed. These tests were
  written after the production code, so passing on the first run proved
  nothing. Stubbing `_detail_is_missing` to always return `False` makes the
  warning vanish (`fires=True` → `fires=False`), so the assertions genuinely
  depend on the implementation

### Phase 5: The reason the artifact already had and never showed

- [x] ✅ **Task 5.1**: `_report_error()` — surface an explanation the tool
  recorded, from a top-level `error` or one nested in `summary`. Two locations
  because the shipped scripts genuinely use both
- [x] ✅ **Task 5.2**: A recorded reason takes precedence over the generic
  count warning. That warning says detail "was dropped", which is false for a
  tool that never ran — see Decision 3
- [x] ✅ **Task 5.3**: RED first this time (4 failed / 52 passed), correcting
  the Phase 4 ordering slip. Producers pinned too: a test reads
  `run_smoke_test.sh` and `run_shell_check.sh` and asserts they still emit the
  shapes these fixtures assume, so the fixtures cannot go stale silently
- [x] ✅ **Task 5.4**: Dogfooded — `--read-only all` over the real reports adds
  ZERO lines on a healthy run

## Technical Decisions

### Decision 1: Fix the `tests` hint, do not exempt it

**Context**: nineteen reports carry a `jq_hint` naming a detail array, so the
array is derivable from the hint. `tests` alone points at `jq '.summary'`,
which yields the counts the summary line has already printed. The guard needs
a rule for that case, and there are two: exempt the report, or fix the hint.

**Exempting it would preserve the exact blindness this plan exists to remove.**
`tests` is not a report that legitimately has no detail — it HAS a `.tests[]`
array, which is where Plan 00226's missing failure names lived all along. The
hint simply does not point at it. An exemption would say "this report has no
reachable detail, and that is fine", which is false, and would leave the one
report with a proven history of losing detail as the one report the guard does
not check.

**Decision**: point the hint at the failing tests. That removes the exception
instead of recording it, makes the guard's derivation uniform across all
twenty reports, and incidentally fixes an operator-facing defect — the current
hint sends a reader who wants detail back to the number they already had.

Safe to change: `findReferences` on `jq_hint` returns only definitions inside
`llm_qa.py` plus one render site, and no test asserts a hint's value.

**Applies in Phase 3**, not here — this plan builds the guard first, so the
fix arrives as the failing test the guard produces (Core Standard 15, and the
sequencing Plan 00228 validated).

**Date**: 2026-08-13

### Decision 2: The count-implies-detail check belongs at RENDER time

**Context**: after Phase 3 the guard was purely structural — it proved WHERE
detail lives (every hint names a real array; no summariser reads elsewhere) but
never opened a report, so a tool emitting `total_violations: 3` beside
`violations: []` passed it clean. That is the plan's own title, unmet.

**Per-tool tests do not cover the gap**: of the twenty tools, six test files
mention `total_violations` at all and two assert the detail array's length. A
new tool would inherit no coverage.

**A test over real report files was considered and rejected.** `llm_qa` runs
tools in registry order and each writes its JSON as it goes, so during a run
the earlier reports are current and the later ones are stale from the previous
run. An assertion over `untracked/qa/` would therefore be order-dependent, and
would only ever fire when QA was already red — which is exactly when nobody is
in a position to act on a flaky test.

**Decision**: check at render time, in `summarize_tool`. It covers every
report including ones nobody has written yet, needs no per-tool opt-in, and
fires precisely when a human or agent is reading the artifact. It follows the
`mismatch_note` precedent already in that function, which warns when the exit
code disagrees with the JSON — the same species of "this report is not
internally consistent" signal.

The warning does not change pass/fail. A dropped detail array is a reporting
defect, and the report has already failed on its own count; inventing a new
failure mode would only obscure the real one.

**Date**: 2026-08-13

### Decision 3: A recorded reason beats an inferred one

**Context**: applying this plan's own lens to the QA scripts turned up two LIVE
instances, not hypotheticals.

- `run_smoke_test.sh` with no daemon socket writes `failed_probes: 3` beside
  `probes: []` and a top-level `error`. The operator sees "0/3 probes passed
  (3 failed)", runs the printed `jq '.probes[]'`, and gets silence.
- `run_shell_check.sh` with shellcheck absent writes `total_issues: 0`,
  `passed: false`, and an error inside `summary`. The line renders as a RED
  "0 issues" with no cause.

Both scripts also print the reason to their own stdout — which `run_tool`
sends to `DEVNULL`. So the only surviving copy is in the JSON, and no
summariser reads it. The information needed to act is on disk and shown to
nobody.

**The second case is why this is not a variant of the count warning.** Its
count is ZERO, so nothing about the count is wrong; what is wrong is that the
check never ran and the artifact does not say so. A guard keyed on counts is
structurally incapable of noticing it.

**Decision**: surface a recorded `error` whenever present, and let it take
precedence over the generic warning. Treating the smoke_test finding as a
CANDIDATE rather than a verdict mattered here — the generic warning would have
told the reader the detail "was dropped", which is untrue when no probes ran.
There was nothing to drop.

**Date**: 2026-08-13

## Success Criteria

- [x] A report claiming a non-zero count with unreachable detail is caught —
  structurally by the guard (a hint naming no detail array, or a summariser
  reading an array the hint does not name) and at render time by the warning
  line for a count with an empty array
- [x] The guard is proven able to fail, against synthesised bad reports: RED
  first on the structural half (2 failed / 46 passed, both `tests`), and by
  MUTATION on the render-time half, which was written after its production
  code and so had to earn its teeth separately
- [x] The `tests` hint gap is closed — pointed at
  `.tests[] | select(.outcome == "failed") | .name`, with the exemption map
  left empty rather than used to excuse it
- [x] All QA passing (20/20, 12634 tests, coverage 95.3%); daemon restart
  verified RUNNING
- [x] An explanation the artifact already holds is never swallowed — added
  after the guard's own lens found two LIVE instances in the shipped QA
  scripts (Decision 3), one of which has a ZERO count and so was invisible to
  the invariant this plan was filed on

## Risks & Mitigations

| Risk                                                                          | Impact | Probability | Mitigation                                                                                             |
| ----------------------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------ |
| The guard asserts against a real run, so it only fires when QA is already red | High   | Medium      | Drive it from synthesised report fixtures, not from whatever `untracked/qa/` happens to hold           |
| A hand-maintained key table drifts from the registry                          | Medium | High        | Derive from `TOOL_REGISTRY` and the `jq_hint`; a hardcoded list is blind to the next report added      |
| An exemption quietly hides a real hole                                        | Medium | Medium      | Every exemption names a report and states a reason, asserted by a test — the pattern Plan 00228 proved |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00229-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed as the follow-up Plan 00226 named for itself, after the dedupe scout
  confirmed no live plan covers QA reporting-fidelity contracts
