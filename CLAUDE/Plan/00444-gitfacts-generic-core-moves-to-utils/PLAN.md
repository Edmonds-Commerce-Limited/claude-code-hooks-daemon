# Plan 00444: gitfacts generic core moves to utils

**Status**: In Progress
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

`plan_qa.gitfacts.GitFacts` is the read-only git plumbing both QA commit gates
use. `docs_qa/context.py` constructs one and `docs_qa/types.py` annotates with
it, which is two of the four `docs_qa`/`utils` → `plan_qa` edges declared in
`tests/integration/test_qa_package_dependency_direction.py`'s `_KNOWN_EDGES`.

The ledger entry that declared them (00422 N14) says `GitFacts` "is the
clearest case — nothing about read-only git plumbing is plan-specific". That
is not quite true, and the difference decides the shape of the fix.
`GitFacts` has eight methods. Seven are generic: `staged_changes`,
`staged_paths_under`, `staged_file_text`, `head_file_text`, `last_commit_date`
and the `_git_output`/`_parse_name_status_z` internals. One is not —
`plan_counter()` delegates to `handlers.utils.plan_numbering.read_plan_counter`,
which is the whole reason the class sits in `plan_qa` at all.

So the move is a split, not a relocation. The generic core becomes
`utils/git_facts.py`; `plan_qa.gitfacts.GitFacts` subclasses it and adds
`plan_counter()`. `docs_qa` — which uses only `staged_changes`,
`staged_file_text` and `head_file_text`, never `plan_counter` — imports the
base and stops depending on `plan_qa` entirely.

## Goals

- `docs_qa` has no import of `plan_qa` except the tier constants in
  `module_doc_budget`, taking `_KNOWN_EDGES` from four entries to two.
- `plan_qa.gitfacts.GitFacts` keeps its exact public surface, so its many
  callers and their tests are untouched.

## Non-Goals

- No change to what any check reports. This is a move plus a subclass.
- `utils/goal_ledger.py` → `PlanDoc` stays declared. Whether a plan-shaped
  utility belongs in `utils` at all is a different question from this one, and
  answering it by moving `PlanDoc` would be the wrong end of it.
- `module_doc_budget` → `plan_qa.types` stays declared: it is deliberate reuse
  of tier constants, and moving those needs a shared home chosen on its own
  merits.

## Tasks

### Phase 1

- [x] ✅ **Task 1.1**: RED — strike the two `gitfacts` rows from
  `_KNOWN_EDGES` and confirm the ratchet's `test_no_undeclared_module_imports_plan_qa`
  fails on exactly those two, proving the guard sees what this plan is
  about to remove.
- [x] ✅ **Task 1.2**: `utils/git_facts.py` with the generic core, plus direct
  tests for it at its new home.
- [x] ✅ **Task 1.3**: `plan_qa.gitfacts.GitFacts` subclasses it, adding only
  `plan_counter()`. Re-export `StagedChange` so no plan-QA caller changes.
- [x] ✅ **Task 1.4**: Repoint `docs_qa/context.py` and `docs_qa/types.py` at
  the base, and correct `context.py`'s prose, which names the plan-QA class
  as the shared one. `tests/unit/plan_qa/conftest.py`'s `run_git`
  monkeypatch moved with the code it patches.

### Phase 2: gate

- [x] ✅ **Task 2.1**: `llm_qa format`, index row and statistics, then
  `llm_qa.py all` green with the daemon restarted after the last `src/`
  edit — 35/35.
- [ ] ⬜ **Task 2.2**: Correct N14 on Plan 00422's `NIGGLES.md` — the entry
  overstates how generic `GitFacts` is — and record the outcome; archive.

## Success Criteria

- [ ] `_KNOWN_EDGES` has two entries, and
  `test_every_declared_edge_still_exists` passes, so the two that went were
  struck off rather than left declared.
- [ ] `plan_qa`'s own `GitFacts` tests pass unchanged — the public surface did
  not move.
- [ ] `llm_qa.py all` green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00444-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
