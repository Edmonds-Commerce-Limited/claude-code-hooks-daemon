# Plan 00310: plan readme completed row ageout

**Status**: Complete
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

- [x] ✅ **Task 1.1**: **Settled rule**: the main `CLAUDE/Plan/README.md`
  "Completed Plans" section retains the **30 highest-numbered** completed
  plan rows (recency by plan number, not by document position — the
  document is roughly but not strictly chronological, e.g. Plan 00116 was
  inserted out of order). Every completed row for a lower-numbered plan
  lives verbatim in the new archive index
  `CLAUDE/Plan/Completed/README.md`, same row shape (link, status clause,
  multi-line sub-bullets moved whole), grouped under one `## Completed Plans (Archive)` heading. Row links inside the archive drop the
  `Completed/` path prefix (the archive file itself already lives inside
  `CLAUDE/Plan/Completed/`, so links are `NNNNN-slug/PLAN.md`, not
  `Completed/NNNNN-slug/PLAN.md`). The main README's "Completed Plans"
  header carries a one-line pointer to the archive. Cancelled section and
  Plan Statistics are untouched by this rule.
- [x] ✅ **Task 1.2**: Enforced via a new test,
  `test_completed_rows_stays_within_the_retention_window` in
  `tests/integration/test_plan_index_navigability.py`, which counts `- [`
  rows in the main README's "Completed Plans" section and fails above 30,
  naming the age-out procedure and the archive path in the assertion
  message. Kept alongside (not replacing) the existing byte-ceiling test.
- [x] ✅ **Task 1.3**: Age-out step documented in the Plan Completion
  Checklist (`CLAUDE/PlanWorkflow.md`, new step 5, checklist renumbered)
  and in `CLAUDE/Plan/CLAUDE.md`'s local conventions.

### Phase 2: Migrate the backlog

- [x] ✅ **Task 2.1**: One-time migration complete: 223 completed rows
  (plan numbers 1-270) moved verbatim into `CLAUDE/Plan/Completed/README.md`;
  the 30 highest-numbered (271-306) stay in the main README. Navigability
  tests pass with large headroom; `plan-qa --sweep` stats unchanged (they
  count folders, not rows).

## Success Criteria

- [x] Main README is under the ceiling with large headroom and holds only
  the retention window of completed rows; every older row is verbatim in
  `Completed/README.md` and linked.
- [x] A future archival that forgets the age-out step fails a test naming
  the procedure.
- [x] `git log` shows no row content lost (verbatim moves only).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00310-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Complete at `fddd6890` (rule settled, retention test added, checklist/local
  conventions documented, backlog migrated, plan_qa row-folder-bijection
  taught to see the archive index)
