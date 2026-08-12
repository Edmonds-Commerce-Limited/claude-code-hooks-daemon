# Plan 00214: magic number scanner blindness

**Status**: Not Started
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

CLAUDE.md Core Standard 9 states: *"NO MAGIC — Zero magic strings or numbers.
Every string literal and numeric value must be a named constant."* The QA check
that enforces it, `scripts/qa/check_magic_values.py`, implements **only
string-shaped rules**: handler-`__init__` keywords, `HookResult` keywords, tool
comparators, event comparators, and handler display names. It has **no numeric
rule of any kind**.

So half of a stated non-negotiable standard has never been enforced. The gap is
invisible in the way blind guards always are: `magic_values` reports `0 violations` on every run, which reads as "the standard is met" rather than "one
half of it is not checked".

This plan exists because of Core Standard 15 (DBF — Defence Before Fix). A
wrong-scope timeout defect was found and fixed by hand; the bug worth fixing is
the guard that could not see it.

## Context & Background

The defect that exposed this was a hardcoded `timeout: float = 5.0` in
`tests/integration/test_daemon_smoke.py::send_hook_event`. It applied a
CONNECT-sized budget to a full DISPATCH round-trip, so the test intermittently
failed under CPU contention while asserting nothing about correctness. It was
the only timeout in that file not using a named `Timeout.` constant — precisely
the shape a numeric rule exists to catch — and it survived because no rule looks
at numbers.

The same investigation found a sibling test permanently `@pytest.mark.skip`-ed
as "times out in test environment", which was also a wrong constant
(`DAEMON_SHUTDOWN` for an operation that is shutdown **plus** startup). Both are
now fixed; neither fix stops the next one.

Two further dispatch-site literals remain in `tests/acceptance/` (`10.0`), and
they are why this plan is not simply "add a rule and be done": a naive rule will
also flag the `1.0` connect-only liveness probes in those same files, which are
**correct by design** and documented as such. Telling those two apart is the
actual design problem.

## Goals

- Extend `check_magic_values.py` with a numeric rule that makes Core Standard 9
  enforceable in full rather than in half.
- Calibrate the rule against the repo's own source and test files before it is
  allowed to block, measuring the false-positive rate the way Plan 00208 did for
  `comment_changelog`.
- Ensure a passing `magic_values` check means the standard is met, not that it
  was only partly examined.

## Non-Goals

- Blanket-banning every numeric literal. `0`, `1`, `-1`, array indices and
  arithmetic identities are not magic, and a rule that flags them would be
  switched off within a day.
- Fixing every existing violation by hand as a precondition. Per the DBF
  corollary, the batch surface matters more than the instance count.
- Touching the correct-by-design connect-probe timeouts.

## Tasks

### Phase 1: Measure the surface before designing the rule

- [ ] ⬜ **Task 1.1**: Enumerate every numeric literal in `src/` and `tests/`,
  grouped by shape (bare int, float, keyword-argument value, comparison operand)
- [ ] ⬜ **Task 1.2**: Classify a sample by hand into genuinely-magic vs
  legitimately-inline, deriving the exemption categories from evidence rather
  than from guesswork
- [ ] ⬜ **Task 1.3**: Record the measured false-positive rate per candidate rule

### Phase 2: Implement the highest-precision rule first

- [ ] ⬜ **Task 2.1**: TDD a numeric rule targeting the shape with the best
  measured precision — a strong candidate is a literal passed to a `timeout=`
  keyword or to `settimeout()`, where a named `Timeout.` constant already exists
- [ ] ⬜ **Task 2.2**: Wire it into `check_magic_values.py` and its JSON output
- [ ] ⬜ **Task 2.3**: Fix the violations it surfaces (the two `10.0` dispatch
  sites in `tests/acceptance/` are known)
- [ ] ⬜ **Task 2.4**: Demote any rule with a non-zero measured false-positive
  rate to advisory rather than shipping it blocking

### Phase 3: Close the batch gap

- [ ] ⬜ **Task 3.1**: Confirm the whole-repo QA check covers files that never
  pass through a Write/Edit, so the rule is not write-time-only
- [ ] ⬜ **Task 3.2**: Correct Core Standard 9's wording if any numeric category
  is deliberately left unenforced, so the standard and the guard agree

## Dependencies

- Related: Plan 00208, whose measure-then-demote method (block only on signals
  with a measured zero false-positive rate across the repo's own files) is the
  method Phases 1 and 2 follow here.

## Success Criteria

- [ ] A numeric magic-value rule exists, is calibrated against measured data,
  and runs in the QA suite
- [ ] The `timeout=` / `settimeout()` literal class is caught automatically
- [ ] The connect-only liveness probes are NOT flagged
- [ ] Core Standard 9 and the checker enforcing it make the same claim

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00214-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Gap identified while fixing the wrong-scope timeouts in commit `90ef405f`
