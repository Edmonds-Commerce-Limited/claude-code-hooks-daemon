# Plan 00574: plan decisions log document

**Status**: Not Started
**Created**: 2026-11-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`PLAN.md` is read in full every session, so `plan-doc-size` bounds it (advisory 18,000 bytes or 350 lines, warning 25,000 or 500, block 35,000 or 900: `src/claude_code_hooks_daemon/plan_qa/types.py:60-62`, `:86-103`; tiers applied at `plan_qa/checks/plan_doc_size.py:105-111`). Long-form decisions are what push plans over those limits. Today the remedy is "extract into a supporting doc such as `DECISIONS.md`" (`CLAUDE/PlanJournalling.md:111-113`), but that doc has no scaffold, no grammar, no lookup and no QA, so every plan invents its own shape.

This plan adds a first-class `PLAN-DECISIONS.md` per plan, pre-created by `mkplan.bash`: an unbounded, long-form log of task-linked decisions with a parseable entry heading, so the decisions for one task can be found by command. `PLAN.md` becomes the front page of tasks and progress and links to decisions instead of embedding them. `JOURNAL/` keeps its role as ad hoc, append-only narrative; the log is for decisions tied to tasks. The three files interlink so each fact lives once.

Full research, entry grammar, rules and rationale: [DESIGN.md](DESIGN.md). It is a supporting doc, so it is unbounded and read on demand (`plan_qa/paths.py:228-236`, `CLAUDE/PlanJournalling.md:47-58`).

## Goals

- `mkplan.bash` creates `PLAN-DECISIONS.md` for every new plan, from a client-owned template.
- Each decision is one heading with a stable id, task id(s), status and decider, parseable by one regex.
- `hooks-daemon plan-decisions <plan> [--task N.N]` returns the decisions for one task.
- Plan QA validates the log (task ids exist, ids unique, supersede links resolve) and imposes no size limit on it.
- Docs and templates reach client installs through the existing deploy paths.

## Non-Goals

- No mass migration of existing plans (a migration recipe is documented, never forced).
- No change to `PLAN.md` size tiers, and no change to `JOURNAL/` append-only rules.
- No new journal category; `decision` already exists (`plan_qa/model.py:369`) and stays valid for ad hoc decisions with no task.

## Tasks

### Phase 1: Grammar and parser

- [ ] ⬜ **Task 1.1**: Settle the entry grammar and status/decider vocabularies in [DESIGN.md](DESIGN.md) sections 2 and 3 (owner review point).
- [ ] ⬜ **Task 1.2**: Add `plan_qa/decisions.py` parser (id, tasks, status, decider, supersedes, body span) beside `plan_qa/model.py`; tests first.
- [ ] ⬜ **Task 1.3**: Classify `PLAN-DECISIONS.md` as its own `PlanFileKind` in `plan_qa/paths.py`, exempt from plan-document rules as supporting docs already are.

### Phase 2: Scaffolding and writer tool

- [ ] ⬜ **Task 2.1**: Add `_PLAN_DECISIONS_TEMPLATE_.md`; `mkplan.bash` copies it into new plan folders, gated on template presence like `_JOURNAL_TEMPLATE_.md` gates `JOURNAL/` (`mkplan.bash:94-101`, `:592-594`).
- [ ] ⬜ **Task 2.2**: Add `mkplan.bash --decision <plan> <task-ids> <status> <body-file> [--supersedes D-N]` that allocates the next id and appends, mirroring `--journal` (`mkplan.bash:506-630`).
- [ ] ⬜ **Task 2.3**: Seed and deploy the template from `install/plan_workflow.py` as a client-owned, never-overwritten asset (`:50-66`, `:348-357`).
- [ ] ⬜ **Task 2.4**: Update `_TEMPLATE_.md` so PLAN.md carries a "Decisions" pointer line and tasks link `D-N`.

### Phase 3: Lookup and QA

- [ ] ⬜ **Task 3.1**: Add `hooks-daemon plan-decisions <plan> [--task N.N] [--status S] [--json]` in `daemon/cli.py`, sibling of `cmd_plan_qa` (`:8609`).
- [ ] ⬜ **Task 3.2**: Add plan-qa checks `decision-task-exists`, `decision-id-unique`, `decision-supersede-resolves`, `plan-links-decisions` (register in `plan_qa/checks/__init__.py`).
- [ ] ⬜ **Task 3.3**: Test that `plan-doc-size` never fires on the log.

### Phase 4: Docs and deployment

- [ ] ⬜ **Task 4.1**: Update `CLAUDE/PlanJournalling.md` (contracts table `:47-58`, remedy 1 `:111-113`), `CLAUDE/PlanWorkflow.md` and `CLAUDE/DirectoryRoles.md:39`; grammar lives in one doc only.
- [ ] ⬜ **Task 4.2**: Update the client copies: `install/templates/core/PlanWorkflow.core.md` (deployed by `install/core_docs.py`) and `install/templates/PlanJournalling.md`.
- [ ] ⬜ **Task 4.3**: Add the optional per-plan migration recipe (DESIGN.md section 7) to `CLAUDE/PlanWorkflow.md`.
- [ ] ⬜ **Task 4.4**: Dogfood: record this plan's own decisions in its `PLAN-DECISIONS.md` once Task 2.1 lands.

## Success Criteria

- [ ] A new plan from `mkplan.bash` contains `PLAN-DECISIONS.md`; `mkplan.bash --decision` appends valid, id-allocated entries.
- [ ] `hooks-daemon plan-decisions <plan> --task N.N` returns exactly that task's decisions, in text and JSON.
- [ ] The four plan-qa checks run in edit, commit and sweep stages; no size check applies to the log.
- [ ] A client deploy and upgrade ships the template and docs without overwriting client-owned files.
- [ ] Unit tests cover parser, checks, `--decision` and the CLI; full QA is green.
- [ ] Holding-area line: a pending-release note records that new plans scaffold `PLAN-DECISIONS.md`, the new `plan-decisions` command and `mkplan.bash --decision`, and that existing plans are untouched.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/YYYY-MM-DD/<entry>.md — see CLAUDE/PlanJournalling.md. -->

- Not started; owner schedules.
