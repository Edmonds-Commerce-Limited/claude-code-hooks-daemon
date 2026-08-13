# Plan 00230: plan-qa reports clean for what it never examined

**Status**: In Progress
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Two plans in the live tree — 00131 and 00132 — carry `**Status**:` values that
are not in the allowed enum (`Shipped v3.23.0 (…)` and
`Pending Proposal — not started`). `status-enum-and-date` is a **BLOCK**-level
check that exists precisely to reject those. The session sweep reports the tree
**clean**, and `plan-qa --lint` on either file — invoked the way the shipped
skill documents it — reports **clean** too.

Neither plan is the bug. The bug is that the plan-QA tooling has two independent
ways of certifying a file it never looked at, and CLAUDE.md Standard 15 (DBF)
says the guard blindness is the defect worth fixing.

**Blindness 1 — `--lint` on a path it cannot classify prints a clean bill of
health.** `classify()` short-circuits to `OUTSIDE` when the path is not
`is_relative_to(context.plan_dir)`, and `plan_dir` is absolute. The CLI passes
`Path(args.lint)` through unresolved, so a **relative** path — the form
`skills/hooks-daemon/plan-qa.md:33` tells clients to type — never matches, every
EDIT-stage check no-matches, and the run prints
`Plan QA: 0 findings — plan tree is clean.` with exit 0. The same file by
absolute path exits 1 with a BLOCK finding. `plan-qa --lint /workspace/README.md`
— not a plan document at all — is also certified clean. The message compounds
it: linting ONE file claims the whole *tree* is clean.

**Blindness 2 — the document-level checks have no batch equivalent, and an
unparseable status falls through a `None` hole.** All 12 single-document checks
are `Stage.EDIT` only; every `Stage.SWEEP` check is tree-level (bijection,
recount, collisions). So no check ever reads a `PLAN.md` already on disk. Worse,
the one sweep check that *does* look at status —
`location-status-coherence` — tests `doc.is_terminal` and
`doc.status in _NON_TERMINAL_STATUSES`; an unparseable status is `None`, which
satisfies neither, so a garbage status token is invisible to the entire sweep.
This is the exact corollary spelled out in CLAUDE.md Standard 15: *a guard that
only fires at write time does not cover what is already on disk — every
write-time rule needs a batch equivalent, or everything predating it is
permanently unexamined.*

## Goals

- `plan-qa --lint` never reports "clean" for a file it did not examine — a
  relative path is resolved, and an unclassifiable target FAILS FAST.
- `--lint`'s report describes what was actually linted (one file), not the tree.
- Every document-level check that is a pure function of on-disk state gains a
  SWEEP twin, so pre-existing violations are examined.
- `location-status-coherence` treats an unparseable status as a finding rather
  than falling through its terminal/non-terminal split.
- 00131 and 00132 carry valid status tokens, fixed *after* the guards can see
  them (guard first, then the instances it surfaces).

## Non-Goals

- No change to `classify()`'s absolute-path contract — hook payloads are always
  absolute and that is correct. The resolution belongs at the CLI boundary.
- No SWEEP twin for checks that are legitimately about the *act of writing*:
  `archive-immutability`, `journal-append-only`, `journal-dayfile-is-today`.
  A day-file dated last week is fine on disk; only writing to it is wrong.
- No new checks, no new policy knobs, no changes to enum membership.

## Context & Background

Verified against the live tree before filing (evidence in `JOURNAL/`):

| Probe                                                   | Result                        |
| ------------------------------------------------------- | ----------------------------- |
| `plan-qa --lint CLAUDE/Plan/00131-…/PLAN.md` (relative) | exit 0, "plan tree is clean"  |
| `plan-qa --lint /workspace/CLAUDE/Plan/00131-…/PLAN.md` | exit 1, BLOCK finding         |
| `plan-qa --lint /workspace/README.md`                   | exit 0, "plan tree is clean"  |
| `plan-qa --sweep`                                       | exit 0, 0 findings            |
| `PlanDoc.parse` on 00131 / 00132                        | `status=None`, `present=True` |

Every existing lint CLI test in `tests/unit/daemon/test_cli_plan_qa.py` passes
an absolute `root / "CLAUDE/Plan/…"` path, so the suite structurally cannot see
Blindness 1 — the tests and the documented usage disagree about the input shape.

## Tasks

### Phase 1: Close the `--lint` false clean

- [x] ✅ **Task 1.1**: RED — add CLI tests that fail today (4 failed / 12 passed)
  - [x] ✅ Relative lint target (CWD-relative) surfaces the same findings as the absolute one
  - [x] ✅ A non-plan-document target exits non-zero with an explicit "not a plan document" message
  - [x] ✅ A clean single-file lint reports the FILE, not "plan tree is clean"
- [x] ✅ **Task 1.2**: GREEN — resolve the lint target at the CLI boundary and
  FAIL FAST when `classify()` returns `OUTSIDE`
- [x] ✅ **Task 1.3**: Fix the report wording so `--lint` never over-claims scope

### Phase 2: Close the `None`-status hole in the sweep

- [ ] ⬜ **Task 2.1**: RED — sweep test: a plan folder whose status is present
  but unparseable produces a finding
- [ ] ⬜ **Task 2.2**: GREEN — handle `status_line_present and status is None`
  explicitly in `location-status-coherence`

### Phase 3: EDIT/SWEEP parity for document-level checks

- [ ] ⬜ **Task 3.1**: Classify all 12 EDIT-stage checks as *batchable* (pure
  function of on-disk state) or *write-act-only*; record the verdict per check
  with its reason, so the split is decided once rather than re-derived
- [ ] ⬜ **Task 3.2**: RED — for each batchable check, a sweep test over a tree
  containing a pre-existing violation
- [ ] ⬜ **Task 3.3**: GREEN — register the SWEEP twin for each batchable check
- [ ] ⬜ **Task 3.4**: Add a guard test asserting the classification is TOTAL —
  every EDIT check is either registered at SWEEP or carries a recorded
  write-act-only exemption, so a future EDIT check cannot be added blind

### Phase 4: Fix the instances the guards now surface

- [ ] ⬜ **Task 4.1**: Run the repaired sweep over the live tree and record every finding
- [ ] ⬜ **Task 4.2**: Fix 00131 and 00132 status tokens (preserving the
  narrative they carry, which belongs after a valid token or in the body)
- [ ] ⬜ **Task 4.3**: Fix any further findings the repaired sweep surfaces
- [ ] ⬜ **Task 4.4**: Sweep exits 0 on the live tree for the right reason

### Phase 5: Verify

- [ ] ⬜ **Task 5.1**: Full QA: `./scripts/qa/llm_qa.py all`
- [ ] ⬜ **Task 5.2**: Daemon restart verification (`restart` then `status` = RUNNING)
- [ ] ⬜ **Task 5.3**: Confirm the shipped skill's documented relative-path
  invocation now behaves correctly

## Technical Decisions

### Decision 1: Fix at the CLI boundary, not in `classify()`

**Context**: `classify()` requires an absolute path; the CLI hands it whatever
the user typed.

**Options**: (a) make `classify()` resolve relative paths itself; (b) resolve at
the CLI boundary.

**Decision**: (b). `classify()` is fed by hook payloads, which Claude Code
guarantees absolute (the `absolute_path` handler enforces it). Teaching it to
resolve relative paths would introduce a CWD dependency into the one module
documented as config-independent and layout-only. The CLI is the only surface
that accepts human input, so validation belongs there.

### Decision 2: An unclassifiable lint target is an ERROR, not a clean result

**Context**: `--lint /workspace/README.md` currently exits 0 clean.

**Decision**: Exit non-zero with a message naming why the file is not a plan
document. FAIL FAST: a lint tool that certifies files outside its remit is worse
than one that refuses them, because the exit code is what CI reads.

### Decision 3: Guard the classification, not just the checks

**Context**: Adding SWEEP twins fixes today's 12 checks; check 13 would be added
blind and the gap would silently reopen.

**Decision**: Task 3.4's totality guard is the actual deliverable of Phase 3.
The twins are the instances; the guard is the defence.

## Success Criteria

- [ ] `plan-qa --lint` with a relative path reports what the absolute path reports
- [ ] `plan-qa --lint` on a non-plan file exits non-zero and says why
- [ ] A pre-existing unparseable status is reported by `--sweep`
- [ ] Every EDIT check is registered at SWEEP or carries a recorded exemption,
  enforced by a test
- [ ] 00131 and 00132 carry valid status tokens
- [ ] `plan-qa --sweep` exits 0 on the live tree
- [ ] Full QA passes; daemon restarts RUNNING

## Risks & Mitigations

| Risk                                                           | Impact | Probability | Mitigation                                                                              |
| -------------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------- |
| New SWEEP twins surface a flood of findings across old plans   | Medium | High        | Expected — that is the point. Triage in Phase 4; `legacy_plan_allowlist` already exists |
| A check assumed batchable actually needs before/after state    | Medium | Medium      | Task 3.1 records a reason per check before any code is written                          |
| Resolving the lint path changes behaviour for absolute callers | Low    | Low         | `Path.resolve()` is a no-op on an already-absolute path; covered by existing tests      |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00230-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed after live-tree probes confirmed both blindnesses
