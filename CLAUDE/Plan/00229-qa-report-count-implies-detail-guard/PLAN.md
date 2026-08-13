# Plan 00229: qa report count implies detail guard

**Status**: Not Started
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

- [ ] ⬜ **Task 1.1**: Enumerate every `TOOL_REGISTRY` entry and record, per
  report, the summary count key, the detail array the SUMMARIZER reads, and
  the detail array the printed `jq_hint` names — the three can differ, and the
  `tests` entry proves it
- [ ] ⬜ **Task 1.2**: Decide the contract's exact wording where a report has
  no detail array by design, so an exemption is explicit and reasoned rather
  than an unnoticed hole

### Phase 2: Build the guard (RED first)

- [ ] ⬜ **Task 2.1**: Failing test: synthesise a report whose summary count is
  non-zero and whose detail array is empty, and assert the guard rejects it
- [ ] ⬜ **Task 2.2**: Vacuity and teeth — assert the registry is discovered
  rather than hardcoded, the in-scope set is non-empty, and every exemption
  names a real report and states a reason
- [ ] ⬜ **Task 2.3**: Implement until green across all twenty reports

### Phase 3: Fix what the guard surfaces

- [ ] ⬜ **Task 3.1**: Treat each finding as a CANDIDATE, not a verdict —
  Plan 00228's first run produced three hits of which only one was a real bug,
  so investigate before changing anything
- [ ] ⬜ **Task 3.2**: Full QA, daemon restart, dogfood live

## Success Criteria

- [ ] A report claiming a non-zero count with unreachable detail FAILS a test
- [ ] The guard is proven able to fail, against a synthesised bad report
- [ ] The `tests` hint gap is closed or exempted with a stated reason
- [ ] All QA passing; daemon restart verified RUNNING

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
