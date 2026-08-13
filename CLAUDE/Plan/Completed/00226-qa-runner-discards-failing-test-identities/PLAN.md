# Plan 00226: QA runner discards failing test identities

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (TDD)

## Overview

When the QA suite goes red it reports HOW MANY tests failed and never WHICH.
The artifact says `tests: 12506 passed, 2 failed` and `tests.json` carries an
empty `tests` array, so the only way to learn what broke is to re-run pytest —
a full suite takes minutes, and `--lf` only helps if the cache survives.

This is guard blindness rather than cosmetics. A QA gate whose red result
cannot be diagnosed from its own output pushes the agent toward re-running, or
worse, toward guessing which change caused it.

## The evidence (hit live 2026-08-13, during Plan 00224 closure)

QA reported `2 failed`. Diagnosis took four steps and still did not fully
succeed:

| step                               | result                                   |
| ---------------------------------- | ---------------------------------------- |
| read `tests.json`                  | counts only; `tests` is `[]`             |
| grep the raw artifact              | already overwritten by the next run      |
| re-run with `--lf`                 | named ONE of the two                     |
| targeted re-runs to find the other | never reproduced; identity still unknown |

One of the two failures remains unidentified. That is the cost of the gap
stated plainly: a real red result whose cause was never determined.

## Root cause

`scripts/qa/run_tests.sh` has two paths:

- **JSON path** (used when `pytest_json_report` is importable) parses per-test
  records and populates `tests`.
- **Text fallback** (used otherwise) scrapes only the count line with three
  regexes and sets `"tests": [],  # Not parsed from text output`.

`pytest_json_report` is NOT installed in this project's venv, so the fallback
is the path that always runs here. Its raw output DOES contain the identities —
pytest prints a short summary of `FAILED <nodeid> - <reason>` lines by default
— and the parser simply does not read them.

## Goals

- A red QA result names the failing tests in its own output
- Works without adding a runtime dependency, so the floor holds in any
  environment
- The parsing is unit-testable, not buried in a shell heredoc

## Non-Goals

- Replacing the JSON path — where `pytest-json-report` IS installed it gives
  richer data and should keep being preferred
- Changing which tests run, or any test's behaviour
- Making `llm_qa.py` print full tracebacks; the node IDs are what is missing

## Tasks

### Phase 1: Reproduce

- [x] ✅ **Task 1.1**: 9 tests covering extraction, count parsing, the
  zero-failure case and degraded input
- [x] ✅ **Task 1.2**: Used REAL captured output, and it mattered — pytest
  colours its short summary even when redirected to a file, and the escape
  codes sit INSIDE the node id (`::\x1b[1mname\x1b[0m`). A fixture written from
  memory would have produced a parser that captured control characters as part
  of every test name

### Phase 2: Implement

- [x] ✅ **Task 2.1**: `qa/pytest_text_report.parse_pytest_text_output()`;
  the shell heredoc now calls it instead of holding the regexes, and runs under
  `VENV_PYTHON` so the module is importable
- [x] ✅ **Task 2.2**: `tests` populated in the same record shape the JSON path
  emits, and `llm_qa.py` names the failures inline, capped at 15
- [x] ✅ **Task 2.3**: Full QA + daemon restart verification

### Phase 3: Make the class detectable (DBF)

- [x] ✅ **Task 3.1**: Asked, and the answer overturned the assumption behind
  the question — see Decision 2. The gap is structural, not pytest-specific
- [x] ✅ **Task 3.2**: Guarded the producer/consumer coupling for THIS check.
  `_summarize_tests` filters on a literal `outcome` token, and nothing tied it
  to the token `run_tests.sh` writes — so a one-word change on either side would
  restore the blindness while the count kept looking healthy. The guard reads
  the token out of the shell script and asserts the summariser renders it, with
  a vacuity check and an inverse test so it cannot pass hollowly. This is
  narrower than Decision 2's follow-up and does not replace it

## Technical Decisions

### Decision 1: Fix the fallback rather than install the plugin

**Context**: The JSON path already populates `tests`. Adding
`pytest-json-report` as a dev dependency would activate it in two lines.

**Why that is not sufficient**: it fixes this venv, not the class. The fallback
exists precisely for environments without the plugin, and would stay blind
there — so the next person to hit this hits it somewhere the plugin is absent.
A guard must not depend on an optional package to be able to report what it
found.

**Decision**: fix the fallback. Installing the plugin remains a separate,
compatible improvement; it is not a substitute.

**Date**: 2026-08-13

### Decision 2: The count/detail split is structural, not a pytest quirk

**Context**: Task 3.1 asked which other QA checks report a count without the
identities behind it. The assumption behind the question was that the other
checks derive their summary FROM their detail array, so the two cannot
disagree, making pytest the odd one out.

**That assumption is wrong.** Every summariser in `llm_qa.py`
(`_summarize_magic_values`, `_summarize_lint`, `_summarize_security`, and the
rest) reads a `summary.total_*` COUNT FIELD. Not one of them reads the detail
array. So a producer that populates its count but not its violations list
produces exactly the pytest failure mode, and nothing in the reporting layer
would notice — the summary would print a non-zero count and the `jq` hint would
lead the reader to an empty array.

**What was actually verified**: the mechanism that permits the disagreement,
by reading every summariser. NOT verified: whether each individual producer
populates its detail array consistently, which would need a red run per check
to exercise. Recorded as a limit on this finding rather than an all-clear.

**Follow-up worth doing, still not done here**: a guard asserting the invariant
`summary count > 0 implies detail array non-empty` across EVERY QA report.
That is the genuine DBF fix for the class. Task 3.2 added a guard for the tests
check only — it binds one producer to one consumer, which is strictly less than
the class-wide invariant. This plan fixes the one instance and names the class
rather than pretending the sweep was complete.

**Date**: 2026-08-13

## Success Criteria

- [x] A red QA run names the failing tests in `tests.json` and in the summary —
  proven by running the heredoc body verbatim against a red raw file, since a
  green QA run cannot exercise the failure listing
- [x] A green run is unchanged (`tests: []`, `failed: 0`)
- [x] The parser is covered by 9 unit tests against REAL captured pytest
  output, escape codes included
- [x] The RENDERING half is covered too — 8 tests on `_summarize_tests`,
  including the producer/consumer token coupling. Found while closing the plan:
  the parser tests and the red-file check both stopped short of the surface an
  LLM actually reads, so a silent rendering break would have passed both
- [x] All QA passing (20/20, 12,537 tests, 95.3% coverage); daemon restart
  verified RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00226-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found by hitting it during Plan 00224 closure; one of the two failures it
  hid was never identified
