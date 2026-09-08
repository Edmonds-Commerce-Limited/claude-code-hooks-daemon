# Plan 00359: the release pipeline checks the slate is clean before it starts

**Status**: Complete
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

The owner asked, mid-session: "are all plans delivered? do we have WIP or is
the slate clean and ready for release?" The honest answer was *not clean*, and
nothing in the release pipeline would have said so. At that moment HEAD was
three commits past the last green CI run (each later run cancelled by the next
push), a known security fail-open had just been filed as Plan 00357, and eight
plans were In Progress. `/release` would have proceeded through every gate,
because every gate it has looks at the CODE — none looks at the STATE OF THE
WORK around it.

The pipeline's only notion of "in flight" today is its own state file
(RELEASING.md "No state file ⇒ no release is in progress"). That protects
against a half-done release. It does not protect against releasing over
half-done work.

This plan adds a **slate-clean gate** to Step 1 (Pre-Release Validation): a
report of everything in flight, and a stop for a human decision when there is
anything to decide. If nothing is in flight, the pipeline proceeds exactly as it
does today — no new prompt, no new pause.

A dedupe scout checked all 44 live plans: nothing covers this. Plan 00330's
"release gate" is a skill-coherence check, a different safety property.

## Goals

- A release cannot begin on a HEAD that CI has not passed. Locally-green is not
  the bar; the exact HEAD sha must have a completed, successful run.
- Everything genuinely in flight is on one screen before the version bump:
  plans mid-work, branches with unlanded commits, live worktrees, and
  high-priority plans still unaddressed.
- A plan that is In Progress ONLY because it is waiting for this very release
  (00102, 00110, 00293 at time of writing) is shown as such and does not block
  — the opposite of a blocker.
- When there is something to decide, the human decides it, and the decision is
  explicit and recorded — not inferred from silence.

## Non-Goals

- **Not** a second confirmation prompt on a clean slate. The `/release`
  invocation is the authorisation and RELEASING.md is explicit that no secondary
  confirmation exists; a clean report proceeds without pausing. The owner's
  "proceed as normal with confirmation" is read as "confirming the slate is
  clean", not as adding a prompt — recorded here so the reading is visible.
- **Not** deciding for the human what in-flight work is acceptable to release
  over. The gate reports; it does not rank. A known security finding and a
  dormant docs plan both appear; which one matters is scope, and scope is the
  human's call (RELEASING.md "A release is a decision about SCOPE").
- **Not** reaping anything. Stale branches and worktrees are listed, never
  touched — `worktree-reap` exists for that and is a separate, deliberate act.

## Context & Background

| Plan  | Title                                  | Status      | Relevance                                                |
| ----- | -------------------------------------- | ----------- | -------------------------------------------------------- |
| 00352 | agent branches outlive their worktrees | Complete    | `collect_orphaned_branches` — NOT reused; see Decision 4 |
| 00144 | Plan QA system                         | Dormant     | `PlanDoc.parse` — reused for status and priority         |
| 00250 | CI runs the blocking acceptance gates  | In Progress | Made CI a real gate; this makes HEAD-green a release one |
| 00330 | skill surface coherence                | Not Started | Its "release gate" is a different property               |

## Technical Decisions

### Decision 1: HEAD-green means the exact sha, completed, successful

A "recent green run" is not enough — the run that mattered here was green on
`218a6a29` while HEAD was `1cdcc2b1`. `in_progress`, `cancelled` and *absent*
are all NOT green. The lookup is injectable so the gate is testable without
`gh`; a lookup failure is reported as "could not determine", which is treated
as not green rather than as clean.

### Decision 2: release-gated plans are recognised by their own words

A plan waiting on the release says so in its status line (`blocked SOLELY on a human running /release`). The gate classifies an In Progress plan as
release-gated when its status text names `/release`. This is a heuristic and is
stated as one: a plan that is mid-work AND mentions `/release` in passing would
be misclassified as waiting. The cost of that error is a plan shown under the
wrong heading in a report a human reads — not a release proceeding unseen — so
the heuristic is acceptable, and a structured token can replace it if it ever
misleads.

### Decision 4: `collect_orphaned_branches` is NOT reused, despite the plan saying it would be

It answers a different question. Plan 00352's helper finds branches whose
WORKTREE has gone; this gate wants branches with commits main does not have,
worktree or not. The listing is two git calls (`for-each-ref`, then
`rev-list --count main..<branch>` per branch) and the test double models
exactly those, so reuse would have meant modelling `branch --merged` and
`branch --list` for a helper whose answer is then discarded. Written directly.

### Decision 3: in-flight stops with a report; proceeding is an explicit re-invocation

The gate exits non-zero with the report. It does not prompt — the pipeline has
no interactive prompts and adding one would change its character. To proceed
over in-flight work the human re-invokes with an explicit acknowledgement
(`accept-wip`), which passes `--accept` to the check: the report still prints,
the exit is 0, and the acknowledgement is in the invocation record. Silence
never proceeds.

## Tasks

### Phase 1: The report

- [x] ✅ **Task 1.1**: RED — `tests/unit/core/test_release_slate.py`: a plan
  tree with In Progress, release-gated In Progress, High Not Started, and
  Complete plans classifies correctly; a HEAD whose run is absent /
  in_progress / cancelled is not green; branches ahead and worktrees are
  listed; the verdict is `clean` only when nothing is in flight.

- [x] ✅ **Task 1.2**: GREEN — `core/release_slate.py`: `collect_slate(...)`
  returning a frozen `SlateReport`, with `run_fn` and `ci_lookup` injected.
  Reuses `PlanDoc.parse`; `collect_orphaned_branches` is NOT reused — see
  Decision 4.

### Phase 2: The gate

- [x] ✅ **Task 2.1**: `bin/hooks-daemon release-slate-check [--accept] [--json]` — exit 0 clean, 2 in flight, 1 could-not-determine. Tests in
  `tests/unit/daemon/test_cli_release_slate_check.py`.

- [x] ✅ **Task 2.2**: RELEASING.md Step 1a names the gate and its three exit
  meanings; the skill's `invoke.sh` runs it as Stage 0 before any agent is
  spawned, stops with the report on 2, and `accept-wip` is the documented way
  to proceed.

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Full QA 25/26 with the one failure black's own
  auto-fix, committed before the tick; the earlier 22/26 run's real findings
  (a direct git spawn in the CI lookup, a short-refname listing, an
  unannotated subprocess import) are each fixed and committed. Daemon
  restarted and RUNNING.

- [x] ✅ **Task 3.2**: Run against this repository as it stood: exit 2, HEAD's
  run `in_progress`, eight plans in flight, 00102 correctly under "waiting for
  this release", six high-priority plans surfaced, eight branches ahead, nine
  worktrees. Two things the live run taught that the fixtures had not: `gh`
  reports a running run's conclusion as `""` rather than `null` (rendered a
  trailing comma — fixed, with a test), and 00110 was filed as in flight
  because its OWN status line did not say `/release` even though the plan is
  release-gated — fixed on the plan, which is where Decision 2 puts the burden.

## Success Criteria

- [x] `release-slate-check` on a HEAD with no completed successful run exits
  non-zero, naming the sha and the run state it found
- [x] An In Progress plan whose status names `/release` is listed as waiting,
  not as in flight
- [x] A clean slate exits 0 and prints nothing that reads as a question
- [x] `accept-wip` proceeds with the report still printed
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/01-release-slate-clean-gate.md`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00359-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from the owner's question, with the state that prompted it recorded in
  the Overview rather than reconstructed later.
- Shipped at `7f0f6f40` (module, CLI command, RELEASING.md Step 1a, skill
  Stage 0), hardened at `268dab5b` (bounded git runner, full refnames).
