# Decision: where a Defence lives — `scripts/qa/` Detector or test?

**Status**: DECIDED — ruling in
[fable-defence-location-decision.md](fable-defence-location-decision.md).
Option A endorsed in direction and corrected in letter: every Defence is a
`scripts/qa/` Detector (method clause 3.2), bound by a `TOOL_REGISTRY` entry, a
real-tree pytest assertion and one generic wiring test — not by a `run_all.sh`
step, which neither the release gate nor CI runs. Governs every remaining class
in this plan.

**Raised by**: Plan 00412 class 15 (`unbounded-work-on-input-not-sized`),
Defence landed as `tests/integration/test_subprocess_spawns_are_bounded.py`.

## The conflict

Two standing rules in this repository give opposite answers, and both are
written down as settled.

**Rule A — `CLAUDE/Security/README.md`, "The obligation this carries"**:

> Every category in the table must name a Defence, and every Defence must be a
> Detector in `scripts/qa/` wired into `run_all.sh` like any other check — not
> a regression test, not a note, not a convention.

It further asserts that both existing categories honour this.

**Rule B — `tests/integration/test_git_spawns_are_bounded.py`, module
docstring**:

> **Why a test rather than a `scripts/qa/` checker**: a test needs no wiring to
> be binding. It runs in the QA suite and in CI by construction, and cannot
> publish its verdict under a key no consumer reads — the failure mode Plan
> 00244 hit with a freshly-added checker.

Rule B is not a stylistic preference. It cites a REAL failure: a checker that
ran, produced a verdict, and gated nothing because no consumer read its key.

## Why this needs deciding once, not per Defence

Sixteen classes remain in this plan, each needing a Defence. Deciding per
Defence produces a split corpus where some classes are registrable and some are
not, and the register's coverage claim becomes unreliable — which is the one
failure a register cannot absorb.

It also creates an `asymmetric-sibling-protection` risk in the register itself:
two Defences for related classes, in two mechanisms, drifting apart.

## Current state, so the decision is made on facts

- Class 15's Defence is a test. It gates the build via `llm_qa.py`'s `tests`
  step, which fails the run.
- It is deliberately **NOT** in the register table. Adding it would make the
  table assert an obligation this Defence does not meet.
- Its sibling (`test_git_spawns_are_bounded`) is also a test, and the two share
  `tests/subprocess_ast.py`. Splitting the pair across two mechanisms would
  reintroduce the divergence that module exists to prevent.

## Options

**A — Adopt the synthesis (recommended).** Defences live in `scripts/qa/` as
Detectors AND each carries a test asserting it is wired into `llm_qa.py`'s tool
table. Satisfies Rule A's letter; the wiring test closes the exact 00244 hole
Rule B cites, converting Rule B from an objection into a requirement.

- Cost: one wiring test per Detector (small, and largely a shared helper).
  Class 15 and the git guard both need migrating, plus the shared AST module
  moves so `scripts/qa/` can import it.
- Risk: low. Nothing about the detection logic changes.

**B — Amend Rule A to permit a test as a Defence.** Cheapest. Register gains a
column naming the mechanism.

- Cost: near zero; class 15 registers as-is.
- Risk: the register's guarantee weakens — "is it wired?" becomes a per-entry
  question again, which is what Rule A existed to stop.

**C — Convert everything to `scripts/qa/`, no wiring test.** Honours Rule A
literally.

- Risk: reintroduces the 00244 failure Rule B recorded. Not recommended.

**D — Leave both mechanisms, register only `scripts/qa/` ones.** The status quo
by default.

- Risk: the register silently under-reports coverage; a reader concludes a
  covered class is uncovered and re-does the work.

## Recommendation

**A.** It is the only option where both documented rules end up true, and the
extra cost is one small test per Defence — cheap against sixteen remaining
classes. If A is chosen, class 15 and the git guard migrate together, because
they share a resolver and must not diverge.

## What I did in the meantime

Followed Rule B's precedent (test), and did NOT register the category. That
keeps the register honest at the cost of it being incomplete, which is the
recoverable direction: an unregistered Defence is found by reading the plan, an
overstated register is trusted and wrong.
