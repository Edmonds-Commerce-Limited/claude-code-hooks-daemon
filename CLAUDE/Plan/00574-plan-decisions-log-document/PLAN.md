# Plan 00574: plan decisions log document

**Status**: Not Started
**Created**: 2026-11-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**Revision**: v2. First draft: [PLAN-v1.md](PLAN-v1.md). Review: [CRITIQUE-v1.md](CRITIQUE-v1.md). Design and dispositions: [DESIGN.md](DESIGN.md).

## Overview

PLAN.md must stay the lean front page of tasks and progress, because it is read in full every session and `plan-doc-size` bounds it (advisory 18,000 bytes or 350 lines, block 35,000 or 900: `src/claude_code_hooks_daemon/plan_qa/types.py:60-62`, `:86-103`). Measurement of the corpus (DESIGN.md section 2) shows decisions are one of three bloat sources: ticked-task "Outcome:" narrative is the largest, then task spec and test lists, then decisions. This plan gives each a named home and makes the daemon's own remedy text point there.

Decisions go in the existing `DECISIONS.md` convention (16 plans, `plan_qa/remedy.py:43-52`): an unbounded supporting doc with a parseable heading carrying a collision-free stamp id, typed refs (`Task 2.3`, `N330`, `plan`), status and decider. JOURNAL/ stays ad hoc and append-only; the log holds task-linked decisions in long form. PLAN.md, `DECISIONS.md` and journal entries link to each other and never restate each other.

Scope is the minimum viable version first (Phases 1 and 2). Writer tool, lookup CLI and extra checks are Phase 3, built only if the documented grep proves insufficient.

## Goals

- One documented heading grammar, one routing rule, one grammar home (the daemon-owned core doc, so existing installs get it).
- Collision-free ids across worktrees with no allocator.
- Size-error and remedy text direct agents to `DECISIONS.md` for decisions, `JOURNAL/` for ticked-task outcome narrative, and a named spec doc for spec lists.
- The shrink guard and the "notepad" hint keep working.

## Non-Goals

- No mass migration; the 16 legacy `DECISIONS.md` files are grandfathered by plan number.
- No change to size tiers or journal append-only rules; no new `PlanFileKind`.
- Not rejected-with-reason: `merge=union` gitattributes and sequential ids (DESIGN.md sections 5, 10).

## Tasks

### Phase 1: Grammar, routing, scaffold

- [ ] ⬜ **Task 1.1**: Finalise grammar and anchored lookup regex (DESIGN.md section 4); owner decides lazy versus pre-created file (DESIGN.md section 6 recommends lazy).
- [ ] ⬜ **Task 1.2**: Write grammar plus routing rule once in `src/claude_code_hooks_daemon/install/templates/core/PlanWorkflow.core.md` and `CLAUDE/core/PlanWorkflow.core.md`; add a one-line grammar comment to `_DECISIONS_TEMPLATE_.md` pointing there.
- [ ] ⬜ **Task 1.3**: Redirect duplicated routes: `CLAUDE/PlanJournalling.md:36-41` row, `:111-113` remedy, contracts table `:47-58`; mirror in `install/templates/PlanJournalling.md`; stop-creating note for `OWNER-RULINGS-*.md` and `DECISION-<topic>.md`.
- [ ] ⬜ **Task 1.4**: Add `**Decisions**:` pointer header to `_TEMPLATE_.md` (both copies); seed `_DECISIONS_TEMPLATE_.md` via `install/plan_workflow.py:50-66` (client-owned); planning-mode path gets the pointer through plan_workflow guidance, no scaffold.

### Phase 2: Agent levers and one check

- [ ] ⬜ **Task 2.1**: Edit `plan_qa/remedy.py`: EXTRACT names `DECISIONS.md` and a `SPEC-*.md`; RELOCATE names ticked-task outcome narrative (keep one line); `plan_doc_size.py` interpolates the plan folder's decisions path.
- [ ] ⬜ **Task 2.2**: Fix `has_staged_supporting_doc` (`plan_qa/checks/common.py:584-614`) to accept a modify of `DECISIONS.md` adding a decision heading; fix `_folder_has_supporting_docs` (`plan_doc_size.py:127-142`) to ignore an entry-less log; tests for both.
- [ ] ⬜ **Task 2.3**: Add `decisions-grammar` check (heading well-formed, ids unique, supersede links resolve) at edit and commit, with the plan-number grandfather threshold; refs-exist advisory at sweep only.
- [ ] ⬜ **Task 2.4**: Test that `plan-doc-size` never fires on `DECISIONS.md`.
- [ ] ⬜ **Task 2.5**: Update `plan_workflow` handler guidance and docs-qa pointers; deploy through core docs and verify an upgrade seeds nothing destructive.

### Phase 3: Later, only if proven necessary

- [ ] ⬜ **Task 3.1**: `mkplan.bash --decision` writer (stamp id, validates refs) and `--decision-init`.
- [ ] ⬜ **Task 3.2**: `hooks-daemon plan-decisions <plan> [--task]` CLI beside `cmd_plan_qa` (`daemon/cli.py:8609`).
- [ ] ⬜ **Task 3.3**: Extend `mkplan.bash --resolve-conflict` to union `DECISIONS.md`; advisory sweep for over-long ticked-task bodies; optional folder-per-decision if conflicts are observed.

### Phase 4: Dogfood

- [ ] ⬜ **Task 4.1**: Record this plan's own decisions (the DESIGN.md section 10 dispositions) in its `DECISIONS.md` after Task 1.2.

## Success Criteria

- [ ] Grammar and routing exist in exactly one daemon-owned doc; other docs link, and the stale JOURNAL routing row is gone.
- [ ] Size findings name `DECISIONS.md`, the JOURNAL outcome home and a spec doc, with the plan folder interpolated.
- [ ] Extraction into an existing `DECISIONS.md` produces no shrink-guard finding; an entry-less log does not silence the notepad hint.
- [ ] `decisions-grammar` passes on a new log and grandfathers plans at or below 00574; no size rule touches the log.
- [ ] Client deploy and upgrade deliver the core doc and template without overwriting client-owned files.
- [ ] Tests cover each changed predicate, the check and remedy wording; full QA green.
- [ ] Holding-area line: a pending-release note records the `DECISIONS.md` grammar, the new routing rule, the reworded size remedy and the grandfathering of existing logs.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/YYYY-MM-DD/<entry>.md — see CLAUDE/PlanJournalling.md. -->

- Not started; owner schedules.
