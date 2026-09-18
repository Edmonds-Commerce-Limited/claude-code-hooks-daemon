# Plan 00439: fence splitter moves out of plan qa

**Status**: In Progress
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

`utils/markdown_links.py` opens by explaining why it lives where it does: "It
lives in `utils` rather than in either subsystem so the dependency runs one
way: both QA packages import it, and it imports neither of them." Six lines
below that sentence is `from claude_code_hooks_daemon.plan_qa.model import lines_outside_fences`. The docstring is not slightly optimistic; it states the
opposite of what the module does.

The import is there because the fence splitter — the primitive that drops
everything inside \`\`\` blocks before a line-oriented check looks at it — was
written for `plan_qa.model` and then needed by everyone else. It now has four
callers, and only two of them are in `plan_qa`: `docs_qa/checks/ at_import_census.py` imports it directly, and `utils/markdown_links.py` imports
it on behalf of every `docs_qa` check that resolves a link. So `docs_qa`
depends on `plan_qa` twice over, by two different routes, for one small
function that belongs to neither.

This plan moves the splitter and its fence regex into a new
`utils/markdown_fences.py`, repoints all four callers, and corrects the one
prose reference in `docs_qa/context.py` that names the old home. No behaviour
changes; the point is that the stated dependency direction becomes the real
one, and the docstring stops contradicting the line beneath it.

This is niggle N5 row (h) of the ledger in Plan 00422.

## Goals

- `lines_outside_fences` and `_FENCE_RE` live in `utils/markdown_fences.py`.
- A test ratchets the `docs_qa`/`utils` → `plan_qa` edge set: the two this plan
  removes are gone, the rest are declared with reasons, and a new one fails.
- `utils/markdown_links.py`'s docstring claim is true of its own imports.
- The splitter gets direct unit tests of its own, which it has never had.

## Non-Goals

- No change to what any check reports — this is a move, not a fix.
- No re-export shim left behind in `plan_qa.model`: a second name for the same
  function is how the ambiguity would survive the move.
- No CLEARING of the other `docs_qa`/`utils` → `plan_qa` couplings. Writing the
  guard found six edges where the ledger entry described one; the other four
  (`utils/goal_ledger.py` → `PlanDoc`, `module_doc_budget` → `plan_qa.types`,
  and two on `plan_qa.gitfacts`) are declared in the guard's allowlist with the
  reason each is still there, and filed as a new ledger entry. They are named,
  not hidden — but moving `GitFacts` is a design question of its own.

## Tasks

### Phase 1: pin the current behaviour

- [x] ✅ **Task 1.1**: Write `tests/unit/utils/test_markdown_fences.py` against
  the new module path — backtick and tilde fences, a tilde fence not closed
  by backticks, an unclosed fence swallowing the tail, indented fences, and
  the delimiter lines themselves being dropped. RED: the module does not
  exist.
- [x] ✅ **Task 1.2**: Write an import-direction test over every module under
  `utils/` and `docs_qa/`. Confirm it is RED against the tree as it stands — a
  guard that has never been seen failing proves nothing. It was RED on **six**
  edges, not the one the ledger described. Rather than narrow the guard to fit
  the plan, it became a ratchet: the four out-of-scope edges are declared in
  `_KNOWN_EDGES` with the reason each survives, a second test fails if a
  declared edge is cleared without being struck off, and an undeclared edge
  fails the first.

### Phase 2: move it

- [x] ✅ **Task 2.1**: Create `utils/markdown_fences.py` holding `_FENCE_RE`
  and `lines_outside_fences`, moved verbatim.
- [x] ✅ **Task 2.2**: Repoint `plan_qa/model.py`, `plan_qa/readme_index.py`,
  `plan_qa/checks/path_existence.py`, `docs_qa/checks/at_import_census.py`
  and `utils/markdown_links.py`; delete the old definition.
- [x] ✅ **Task 2.3**: Correct the prose in `docs_qa/context.py` and
  `plan_qa/readme_index.py` that names `plan_qa.model.lines_outside_fences`.
  `context.py`'s sentence was wrong twice over: it cited `docs_qa.corpus` as
  the reusing module when the reuse is in `at_import_census`.

### Phase 3: gate

- [x] ✅ **Task 3.1**: `scripts/qa/llm_qa.py all` green (35/35), daemon
  restarted before the commit. The first run came back 32/35 for one cause in
  three costumes: black auto-fixed `plan_qa/model.py` mid-run (the blank-line
  gap left by removing `_FENCE_RE`), which moved the working-tree fingerprint
  past the pre-run daemon restart, so acceptance errored 18 times and
  `smoke_test` scored 0/3 on STALE DAEMON. Restarting against the settled tree
  and re-running the three gates: format 0 violations, acceptance 3055 passed,
  smoke_test 3/3.
- [x] ✅ **Task 3.2**: Release note under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] ⬜ **Task 3.3**: Record the outcome on row (h) of Plan 00422's
  `NIGGLES.md`, then archive this plan. The wider finding is filed there as
  **N14**.

## Success Criteria

- [x] ✅ The import-direction test from Task 1.2 is green, and was seen RED
  first — on six edges, of which this plan removes the two it declared.
- [x] ✅ Nothing under `utils/` or `docs_qa/` imports `plan_qa` except the four
  edges declared in `_KNOWN_EDGES`, each with its reason.
- [x] ✅ `llm_qa.py all` reports 35 gates passing (32 in one run, the other
  three re-run green after the stale-daemon restart).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00439-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
