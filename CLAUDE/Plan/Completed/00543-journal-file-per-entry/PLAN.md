# Plan 00543: journal file per entry

**Status**: Complete
**Created**: 2026-10-21
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #135

## Overview

A plan's journal is one file per plan per day (`JOURNAL/NNNNN-Journal-YY-MM-DD.md`), appended by
`mkplan.bash --journal`. Any two branches that journal the same plan on the same day therefore edit the same path,
and the merge conflicts every time: either both create the file, or both append at its end. In one client repository,
44 of 53 conflicted merges conflicted only inside the plan directory, and 44 of the 51 conflicting paths were journal
day-files (#135). `--resolve-conflict` repairs a conflict after the fact; nothing prevents it.

The owner ruled: one file per day "is causing all kind of merge issues, not worth it - file per entry in folder is a
lot cleaner and solves lots of problems". This is #135's Proposal 2. Proposal 1, a merge driver, is not built.

Each `--journal` call writes one NEW file. Files are only ever added, so concurrent branches cannot conflict, and
append-only becomes "no existing entry file is modified or deleted".

## Goals

- `mkplan.bash --journal` writes one file per entry under a per-day folder, for example
  `JOURNAL/YYYY-MM-DD/HHMMSSZ-<category>-<random>.md`. The name sorts by UTC time and cannot collide.
- Every journal reader and check works on the new layout and on legacy day-files side by side: plan QA (ordering,
  append-only, freshness, completion entry), `journal-entry-with-progress`, `same-commit-plan-doc`, and the
  today-only guard. The today-only guard becomes "an existing entry file is never edited".
- `R-JOURNAL-HAND-WRITTEN-ENTRY` still allows only the stamping tool to create entries.
- Every doc and template that names the day-file path describes the new layout: `CLAUDE/PlanJournalling.md`, the plan
  template, the handler guidance, and the generated CLAUDE.md blocks.

## Non-Goals

- Rewriting existing day-files. They stay where they are, read-only, and are read alongside the new entries.
- A git merge driver (#135 Proposal 1).
- Journal redaction (#108, Plan 00516). Under this layout a redaction replaces one entry file, so Plan 00516 must be
  re-scoped onto it. That is noted on 00516, not done here.

## Tasks

### Phase 1: Design check

- [x] ✅ **Task 1.1**: Map every reader, writer and check that knows the day-file name or path pattern: `mkplan.bash`,
  the `plan_qa` checks, `plan_journal_guard`, the plan workflow handlers, and docs. Record the map and the chosen entry
  file name in `DESIGN.md`. Decide how a legacy day-file and new entries are interleaved when read in time order.

### Phase 2: Build (TDD)

- [x] ✅ **Task 2.1**: `mkplan.bash --journal` writes per-entry files, stamped with the real UTC time by the tool alone.
- [x] ✅ **Task 2.2**: Plan QA checks, the guard and the workflow handlers read both layouts. Their invariants hold on
  mixed trees, and a modified or deleted entry file is denied.
- [x] ✅ **Task 2.3**: Update the docs, template and generated guidance.
- [x] ✅ **Task 2.4**: Proof. Two branches journal the same plan on the same day and merge cleanly. A test does this in a
  scratch repository with `git merge-tree`.

## Success Criteria

- [x] Two branches that each journal the same plan on the same day merge with no conflict (tested, Task 2.4).
- [x] Every journal check passes on a tree with legacy day-files and new entries side by side (tested, Task 2.2).
- [x] No doc still tells an agent to write to a day-file (wording sweep merged `c05b91eeb`).
- [x] Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/009-plan-journal-is-one-file-per-entry.md` (the
  pending-release holding area).

## Delivery & Milestones

- Filed from #135 on the owner's direction. Related: Plan 00163, which designed the day-file model and which this
  plan supersedes for new entries, and Plan 00516 (#108), which now carries a re-scope note (`f6a3f00d0`).
- Delivered: merged to main at `c127d7356`, wording sweep `c05b91eeb`; CI green on `15127181d`. Fixes ledger N524.
