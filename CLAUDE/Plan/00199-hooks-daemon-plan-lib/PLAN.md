# Plan 00199: hooks daemon plan lib

**Status**: Not Started
**Created**: 2026-08-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Interpretation

The request was "a plan for hooks-daemon-plan-lib" with no further detail. This
plan takes that to mean: **evaluate extracting this repo's plan/planning
subsystem into a standalone reusable library, usable outside the hooks daemon**
— the "lib" in the name being the operative word. The codebase supports that
reading: `plan_qa/` is already written as a daemon-decoupled rule engine with
its own defaults, and its own docstring says so (`plan_qa/types.py:43`,
`plan_qa/context.py:3-6`).

**If that is the wrong reading, this is the sentence to correct.** Plausible
alternatives the investigation did not find evidence for: a plan for a *new*
planning feature; a plan for the `mkplan.bash`/journalling toolchain
specifically; or documentation work on the plan system.

The investigation reached an answer that is **the opposite of what the name
implies**, so read the Overview before the Tasks.

## Overview

The extraction is **not recommended now**. The evidence for that is not "it
would be hard" — it is the reverse. `plan_qa/` is already a clean library: 42
modules, 4,406 LOC, 30 checks, and exactly **two** imports from the rest of the
daemon, both in one file (`plan_qa/gitfacts.py:23-24`). No pydantic, no
`Handler`, no `HookResult`, no `ProjectContext`. Config is bound by structural
`Protocol`s (`plan_qa/context.py:29-107`) rather than imports, and the package
ships its own policy defaults (`plan_qa/types.py:38-59`) so it runs with no
config source at all.

Because the seam already exists, packaging it separately buys almost nothing
today and costs a permanent second release train, a version-compatibility
matrix between library and daemon, and a split test suite — for **zero
identified consumers**. No plan, doc or issue in this repo proposes extraction
(§10 of the coupling analysis). Under this project's own YAGNI and PROPER NOT
QUICK principles, that is a make-work migration.

What *is* worth doing is small and unambiguously valuable: fix the one genuine
layering defect (`plan_qa` importing upward from `handlers/`), delete the
trivial constant coupling, and add a QA check that **mechanically enforces** the
boundary so it cannot silently rot. That work is a strict prerequisite for
extraction anyway, so it is not throwaway — it converts a boundary that happens
to be clean today into one that is guaranteed clean tomorrow, and leaves
extraction as a small, mostly-mechanical follow-up if a real consumer ever
appears.

Detailed evidence with `file:line` citations: see
[COUPLING-ANALYSIS.md](COUPLING-ANALYSIS.md).

## Goals

- Decide extract-vs-keep on evidence, and record the decision with its trigger
  conditions so it can be revisited without re-doing the investigation
- Remove both cross-package imports from `plan_qa/`, leaving it importing
  stdlib only
- Fix the layering inversion: `plan_qa` must not import from `handlers/`
- Add an automated import-boundary check to the QA suite so the seam is
  enforced, not merely observed
- Leave `plan_qa/` in a state where extraction is a mechanical follow-up

## Non-Goals

- Publishing a `plan-qa` package to PyPI, or creating a second repo
- Splitting the test suite or creating a second release train
- Changing any check's behaviour, any finding's text, or any config key
- Refactoring the hook adapters (`plan_qa_edit`, `plan_qa_commit_gate`,
  `plan_qa_sweep`) — they are already thin (`plan_qa_edit.py:95-124`)
- De-duplicating `mkplan.bash` against `plan_numbering.py` — real, deliberate,
  and a separate concern (COUPLING-ANALYSIS.md §8)
- Extracting the provisioning layer (`install/plan_workflow.py`) — installer
  plumbing, least extractable and least worth extracting

## Context & Background

The plan subsystem is four layers with very different coupling profiles, and
treating it as one thing is what makes it look tangled:

| Layer                | Location                | Daemon coupling          |
| -------------------- | ----------------------- | ------------------------ |
| **A. Rule engine**   | `plan_qa/`              | 2 imports                |
| **B. Hook adapters** | 9 handlers + advisor    | Total, by definition     |
| **C. CLI**           | `daemon/cli.py`         | 2 call sites             |
| **D. Provisioning**  | `install/plan_workflow` | Config model + installer |

Only layer A is library-shaped. Layer B *must* couple — it implements the
daemon's `Handler` ABC. Layer C (`cli.py:3357-3452`) already accepts an
explicit `--project-root` and exits 1 on findings, so plan QA is **already**
usable in CI and as a pre-commit hook today via
`hooks-daemon plan-qa --sweep`. That materially weakens the strongest argument
for extraction, because the headline consumer use case is already served.

## Tasks

### Phase 1: Decision and record

- [ ] ⬜ **Task 1.1**: Confirm the interpretation with the requester before any
  code changes — this plan inverts the outcome the plan name implies
- [ ] ⬜ **Task 1.2**: Record Decisions 1-3 below as the standing answer, with
  the revisit triggers, so a future session does not re-litigate from scratch

### Phase 2: Remove the coupling (TDD)

- [ ] ⬜ **Task 2.1**: Write a failing test asserting `plan_qa/` imports no
  `claude_code_hooks_daemon` module outside `plan_qa` (AST-walk over the
  package; RED against `gitfacts.py:23-24`)
- [ ] ⬜ **Task 2.2**: Replace the `Timeout` import (`gitfacts.py:23`) with a
  module-level `Final[int]` constant in `plan_qa`, defaulted to today's value
- [ ] ⬜ **Task 2.3**: Move the plan-counter reader into `plan_qa` — relocate
  `read_plan_counter` (`handlers/utils/plan_numbering.py:126-139`) and its
  git-config accessor so `plan_qa` owns it, and have `plan_numbering` re-export
  or delegate rather than duplicating
- [ ] ⬜ **Task 2.4**: Verify no behaviour change — the counter must still
  resolve `hooksdaemon.latestPlanNumber` identically for `counter-sanity`
  (`plan_qa/checks/counter_sanity.py`) and `mkplan.bash`
- [ ] ⬜ **Task 2.5**: Confirm the Task 2.1 test now passes (GREEN)

### Phase 3: Enforce the boundary

- [ ] ⬜ **Task 3.1**: Promote the import-boundary test into the QA suite so a
  future daemon import into `plan_qa` fails CI, not just review
- [ ] ⬜ **Task 3.2**: Add a second assertion that `plan_qa` imports no
  third-party package (it currently uses stdlib only — `pyproject.toml:28-35`
  lists six runtime deps, none of which `plan_qa` needs)
- [ ] ⬜ **Task 3.3**: Document the boundary contract in the `plan_qa/__init__`
  docstring: stdlib only, no daemon imports, config via `Protocol`

### Phase 4: Verification

- [ ] ⬜ **Task 4.1**: Full QA — `./scripts/qa/run_all.sh` (all 10 checks)
- [ ] ⬜ **Task 4.2**: Daemon restart verification — `./bin/hooks-daemon restart`
  then `status` shows RUNNING (catches import errors unit tests miss)
- [ ] ⬜ **Task 4.3**: Exercise all three surfaces against this repo's own plan
  tree: `plan-qa --sweep`, `--check-staged`, `--lint <PLAN.md>`
- [ ] ⬜ **Task 4.4**: Confirm the 527 plan-QA tests still pass unchanged — any
  test edit needed is a signal that behaviour moved, which is out of scope

## Dependencies

- Depends on: none
- Blocks: any future extraction plan (Phases 2-3 are its prerequisites)
- Related: the `mkplan.bash` / `plan_numbering.py` duplication
  (COUPLING-ANALYSIS.md §8) — deliberate, separate, not addressed here

## Technical Decisions

### Decision 1: Separate package vs. optional extra vs. in-tree enforced boundary

**Context**: If `plan_qa` is a library, how should it be distributed?

**Options considered**:

1. **Separate distribution** (own repo or own wheel). Real reuse outside the
   daemon; independently versionable. Costs a second release train, a
   compatibility matrix against the daemon, split CI, and a split test suite —
   permanently, for every future change. The daemon would consume its own
   subsystem across a version boundary, so a check change becomes a two-repo
   dance with a release in between.
2. **Optional extra** (`pip install claude-code-hooks-daemon[plan-qa]`).
   Solves nothing here: the package is *already* dependency-free
   (stdlib only), so there is no install weight to make optional. Extras exist
   to gate heavy or conflicting dependencies, and there are none.
3. **In-tree module with a mechanically enforced boundary**. No packaging cost,
   no release-train cost, single test suite. Delivers the property that
   actually matters — the boundary cannot rot — and leaves option 1 open as a
   near-mechanical follow-up because the package would already be import-clean.

**Decision**: Option 3. Options 1 and 2 both pay a permanent, recurring cost to
buy a benefit no identified consumer has asked for. Option 3 buys the durable
part of the benefit (an enforced seam) at small one-off cost, and is a strict
prerequisite for option 1, so nothing is wasted if the decision later flips.

### Decision 2: Which direction should the dependency run?

**Context**: `plan_qa/gitfacts.py:24` imports `read_plan_counter` from
`handlers/utils/plan_numbering.py`. Something must move; which way?

**Options considered**:

1. **Leave it.** Zero work, but it is a genuine layering inversion — the rule
   engine reaching upward into the handlers package — and it is the single
   reason `plan_qa` is not already stdlib-pure. It also blocks any future
   extraction, since `handlers/` cannot come along.
2. **Duplicate the counter reader** into `plan_qa`. Removes the edge but
   creates a third copy of the counter logic (Python × 2 + bash × 1), and the
   whole point of `plan_numbering.py` is to be the single Python source of
   truth. Directly violates DRY and SINGLE SOURCE OF TRUTH.
3. **Move it down into `plan_qa`** and have `plan_numbering` delegate. The
   dependency then runs handlers → `plan_qa`, matching every other layer.
   Nothing about `read_plan_counter` is handler-specific — it reads a git
   config key and parses an int (`plan_numbering.py:126-139`, 14 lines).

**Decision**: Option 3. It is the only one that both removes the inversion and
keeps one Python source of truth. The counter is a *plan* concept, not a
*handler* concept, so `plan_qa` is its correct home; its current location is
historical.

### Decision 3: Should the daemon consume the library, or the library the daemon?

**Context**: Whatever the packaging, the direction of the runtime relationship
must be explicit, because it decides where config lives.

**Options considered**:

1. **Library consumes daemon config.** Would require `plan_qa` to import
   pydantic and the `Config` model — exactly the coupling `context.py:3-6`
   deliberately avoids.
2. **Daemon consumes library, passing policy as plain values.** Already how it
   works: `QaPolicy`/`JournalPolicy`/`PlanDocSizePolicy`
   (`context.py:29-107`) are structural `Protocol`s satisfied by the pydantic
   models without either side importing the other.

**Decision**: Option 2, unchanged — this decision is recorded to make an
existing implicit contract explicit and to stop a future change from
"simplifying" the Protocols into a direct import. `PlanWorkflowQaConfig`
(`config/models.py:519-600`) satisfies the Protocol structurally; the daemon
owns config, the library owns rules, and neither imports the other.

## Why this might not be worth doing

The strongest case against this plan:

- **It is a solution looking for a problem.** The boundary is clean *today*
  with no enforcement. The check in Phase 3 defends against a hypothetical
  future violation, which is itself a YAGNI risk — the exact charge this plan
  levels at extraction. Two of the four phases exist to protect a property that
  has not yet been broken.
- **The coupling is two lines.** One is a constant. Calling that a "layering
  inversion" is technically correct but rhetorically inflated; a reviewer could
  reasonably say the honest fix is a one-line comment, not a four-phase plan.
- **Task 2.3 touches shared code.** `plan_numbering.py` is used by
  `plan_number_helper`, `validate_plan_number` and `markdown_organization`.
  Moving a function out of it to fix a purely aesthetic import direction risks
  a real regression in working code, trading concrete risk for abstract
  tidiness — and `mkplan.bash` reads the same counter independently, so a
  subtle divergence would surface as wrong plan numbers, a loud failure.
- **Phase 3 could be one grep in an existing check.** A whole new QA check may
  be more machinery than the invariant deserves.

**Where that leaves it**: the case is strong enough to kill Phases 3-4 as
standalone work, but not Phase 2 — an inverted dependency is a real defect
that will otherwise be copied by the next module. The proportionate response
is Phase 2 plus the cheapest possible enforcement, and to treat Phase 3's
scope (new check vs. assertion inside an existing one) as a judgement call at
implementation. If the requester wants extraction *itself*, this plan's answer
is "not yet, and here is what would have to be true first" — recorded in
Decision 1 with its revisit triggers, not silently dropped.

## Success Criteria

- [ ] The extract-vs-keep decision is recorded with explicit revisit triggers
- [ ] `plan_qa/` imports no `claude_code_hooks_daemon` module outside itself
- [ ] `plan_qa/` imports no third-party package (stdlib only)
- [ ] The boundary is enforced by an automated check, not convention
- [ ] No layering inversion remains: nothing in `plan_qa` imports `handlers/`
- [ ] All 527 plan-QA tests pass **without modification**
- [ ] Full QA passes and the daemon restarts to RUNNING
- [ ] All three plan-QA surfaces behave identically to before

**Revisit trigger for extraction** — reopen Decision 1 when any of these is
true: a concrete consumer outside this daemon is identified; a second tool in
this org needs the checks; or a user asks to run plan QA without installing the
daemon (note: `plan-qa --sweep --project-root X` may already satisfy this).

## Risks & Mitigations

| Risk                                                               | Impact | Probability | Mitigation                                                                                       |
| ------------------------------------------------------------------ | ------ | ----------- | ------------------------------------------------------------------------------------------------ |
| Moving `read_plan_counter` breaks plan numbering                   | High   | Low         | TDD; `plan_numbering` delegates rather than duplicating; verify against `mkplan.bash` (Task 2.4) |
| Counter behaviour diverges between Python and `mkplan.bash`        | High   | Low         | Task 2.4 explicitly checks both readers resolve the same key identically                         |
| Boundary check produces false positives on `TYPE_CHECKING` imports | Low    | Medium      | AST-walk must treat `TYPE_CHECKING` blocks correctly (`plan_qa/types.py:17-20` uses them)        |
| Scope creep into extraction proper                                 | Medium | Medium      | Non-Goals list it explicitly; Decision 1 gates it behind named triggers                          |
| This plan is judged not worth doing at all                         | Low    | Medium      | "Why this might not be worth doing" argues that case; Phase 1 confirms before any code changes   |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00199-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan authored; investigation complete, recommendation is **do not extract**
