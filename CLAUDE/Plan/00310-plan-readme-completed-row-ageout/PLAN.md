# Plan 00310: plan readme completed row ageout

**Status**: Not Started
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The plan index `CLAUDE/Plan/README.md` breached its 130,000-byte
navigability ceiling twice in one day. Measured cause: of ~130KB, the
Completed Plans section is ~107KB — 253 completed rows (many with
multi-line sub-bullets) that accumulate forever, while the Active section
is only ~18KB. Every plan completion appends a permanent row, so the
ceiling is structurally guaranteed to keep firing and every breach costs a
manual compaction commit.

Owner ruling: completed rows must AGE OUT of the main README. A done-and-old
plan does not need a row in the index every session reads — it needs to be
findable. The main README keeps recent completions (fresh context that
sessions actually reference); older completed rows move to a secondary
archive index that is only opened when someone is digging.

## Goals

- A deterministic age-out rule (recency by plan number is the natural key —
  e.g. keep the most recent ~30 completed rows in the main README; older
  rows live in `Completed/README.md`), applied going forward at every plan
  archival.
- One-time migration of the current backlog under the same rule, taking the
  main README comfortably under the ceiling with headroom.
- The rule is enforced/automated, not remembered: plan QA (or the
  navigability test) tells you when an archival should have aged rows out,
  and the Plan Completion Checklist documents the step.
- Nothing is deleted: every aged-out row moves verbatim to the archive
  index; statistics stay in the main README.

## Non-Goals

- Changing the Active Plans section, statistics, or the Cancelled section's
  location (Cancelled is small; move it only if trivially symmetrical).
- Raising the 130KB ceiling (the ceiling is doing its job — the content
  distribution is the defect).
- Rewriting row content during migration (verbatim moves only).

## Tasks

### Phase 1: Rule design and enforcement hook

- [ ] ⬜ **Task 1.1**: Fix the rule precisely: retention count (proposed:
  the 30 highest-numbered completed plans stay in the main README), the
  archive index location (`CLAUDE/Plan/Completed/README.md`), its format
  (same row shape, grouped as-is), and the link from the main README's
  Completed section header to the archive index. Record in PLAN.md (this
  section) once settled.
- [ ] ⬜ **Task 1.2**: Enforce it: extend `test_plan_index_navigability.py`
  (or plan QA's stats/index checks) so a main README holding more than the
  retention count of completed rows FAILS with a message naming the
  age-out procedure — the same discoverable-failure pattern as the size
  ceiling, but firing on the cause rather than the symptom.
- [ ] ⬜ **Task 1.3**: Document the age-out step in the Plan Completion
  Checklist (`CLAUDE/PlanWorkflow.md`) and `CLAUDE/Plan/CLAUDE.md`'s local
  conventions: on archival, add your row, then move any rows beyond the
  retention count to the archive index in the same commit.

### Phase 2: Migrate the backlog

- [ ] ⬜ **Task 2.1**: One-time migration: move all completed rows beyond
  the retention count, verbatim, into `Completed/README.md`; link it from
  the main README; verify the navigability test passes with real headroom
  (target: main README well under 60KB) and plan QA sweep stays clean
  (stats unchanged — they count folders, not rows).

## Success Criteria

- [ ] Main README is under the ceiling with large headroom and holds only
  the retention window of completed rows; every older row is verbatim in
  `Completed/README.md` and linked.
- [ ] A future archival that forgets the age-out step fails a test naming
  the procedure.
- [ ] `git log` shows no row content lost (verbatim moves only).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00310-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
