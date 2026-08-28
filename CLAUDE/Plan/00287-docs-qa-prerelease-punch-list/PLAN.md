# Plan 00287: docs-qa pre-release punch list

**Status**: In Progress
**Created**: 2026-08-28
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00284 shipped the documentation SSoT enforcement system (`docs_qa`) with
verdict "GOOD WITH NITS — ready for release" from a post-completion Fable
review (`CLAUDE/Plan/Completed/00284-documentation-ssot-enforcement/REVIEW-final-fable.md`).
The review found the design sound but named four mechanical defects that
should land before the staged v3.57.0 manifest promotes
`documentation.enabled` with `recommended: true`, plus one cheap doc-shipping
nit. This plan is that pre-release punch list.

The four MUST-FIX items are all bounded, mechanical fixes to already-shipped
code: a CLI call site missing an argument (F1), two checks that never learned
to consult an allowlist the rest of their siblings already honour (F2), an
exclusion set that stopped one directory-name short of the client-scaling
hazard it was created to prevent (F3), and a reference doc that was never
written for the new handlers (F4). None requires design rework. This plan
also folds in a handful of cheap robustness nits the same review flagged
(unguarded reads in sweep checks, two stale phrasing issues in
`DocumentationStrategy.md`) since they are small enough to fix alongside.

Several review findings are deliberately deferred rather than fixed here —
see Non-Goals — because each is either a structural refactor with no
functional bug attached, or would touch shared code used by a sibling
plan_qa surface and deserves its own scoped plan rather than a punch-list
drive-by.

## Goals

- Fix F1: `docs-qa --lint` must report the SAME severity as the EDIT-stage
  handler for identical unchanged content (pass `file_content_before`).
- Fix F2: `at-import-census` and `module-doc-budget` must honour
  `grandfather_allowlist` in block mode, like every other block-eligible
  check.
- Fix F3: exclude common vendored/build directory names from the doc corpus
  scan, and stop `module-doc-budget`'s sweep from physically descending into
  heavy excluded directories.
- Fix F4: document `docs_qa_edit`, `docs_qa_commit_gate`, `docs_qa_sweep` and
  the `documentation:` config block in `docs/guides/HANDLER_REFERENCE.md`, at
  a depth comparable to the existing `plan_qa` trio.
- Fix N1: make the shipped `docs-qa` skill's stated report-output location
  match its agent template, and redeploy the dogfood copy.
- Fix the cheap nits: guard the unreadable-file case in the sweep checks
  that read files directly from disk; correct two stale phrasing issues in
  `CLAUDE/DocumentationStrategy.md`.
- Re-run `bin/hooks-daemon docs-qa --sweep` after F2/F3 land and report the
  finding-count delta against the 34 advisories the review measured.

## Non-Goals (deferred — tracked, not dropped)

- [ ] **N2 — structural block-eligibility enforcement**: `docs_qa/types.py`'s
  `CheckContext.file_exists_before` is declared but no check reads it; F1 is
  exactly the failure this allows to happen again at a future call site.
  Making worse-only checks branch on an explicit field (and fail fast when
  it is absent at EDIT stage) is a cross-cutting `types.py`/runner change
  touching every check module, not a punch-list-sized fix.
- [ ] **N3 — deduplicate the ~90-line git-commit-command parsing** shared
  verbatim between `docs_qa_commit_gate.py` and `plan_qa_commit_gate.py`
  (plus `_matches_allowlist` ×5, `_is_rules_file` ×2, the `index.json` cache
  path spelled out ×4, and mode-token literals). This touches the sibling
  `plan_qa` surface too and deserves its own scoped refactor plan so the two
  systems are extracted together rather than one drifting from the other.
- [ ] **N3b — unify the three divergent `ssot-quote` marker regex
  spellings** (`quotes.py`, `structured_blocks.py`, `module_doc_budget.py`)
  into one shared pattern, so a marker with unusual spacing is treated
  identically by every consumer.
- [ ] **N5b — `plan_promotion_disposition` re-fires on every later commit**
  touching an already-terminal `PLAN.md` rather than only on the flip to
  terminal (never compares against HEAD, though `gitfacts.head_file_text`
  is available and `rules_file_orphan_shrink` already does exactly that
  comparison). A behavioural change to a shipped advisory check, not a
  bounded mechanical fix.

## Tasks

### Phase 1: F1 — CLI lint severity inflation

- [x] ✅ **Task 1.1**: Regression test proving `cmd_docs_qa --lint` and the
  EDIT-stage handler disagree on severity for identical unchanged content
  (RED).
- [x] ✅ **Task 1.2**: Pass `file_content_before=lint_content` in
  `cmd_docs_qa`'s `--lint` branch (daemon CLI) so an on-disk lint is treated
  as "no pending change" (GREEN).
- [x] ✅ **Task 1.3**: Confirm the fix via `rules-file-shape` and
  `module-doc-budget` worse-only fixtures through the CLI.

### Phase 2: F2 — grandfather allowlist ignored by two checks

- [x] ✅ **Task 2.1**: Failing tests: a grandfathered file's new `@`-import
  and a grandfathered file's new-over-budget module doc must downgrade to
  ADVISE in block mode.
- [x] ✅ **Task 2.2**: Add `grandfather_allowlist` consultation to
  `at_import_census.py` (mirrors `pointer_resolves.py`'s pattern).
- [x] ✅ **Task 2.3**: Add `grandfather_allowlist` consultation to
  `module_doc_budget.py` (mirrors `rules_file_shape.py`'s pattern).

### Phase 3: F3 — client-scaling exclusions

- [x] ✅ **Task 3.1**: Failing tests: `corpus._is_excluded` must exclude
  common vendored/build directory names inside the configured trees
  (`node_modules`, `dist`, `build`, `target`, `.venv`, `.next`,
  `third_party`, in addition to the names already covered elsewhere).
- [x] ✅ **Task 3.2**: Extend `corpus._is_excluded` with the missing names
  (added a shared `COMMON_VENDORED_BUILD_DIR_NAMES` constant).
- [x] ✅ **Task 3.3**: Failing test: `module_doc_budget`'s sweep must not
  physically descend into an excluded directory (assert on pruning via a
  spying `os.walk`, not just post-filtering).
- [x] ✅ **Task 3.4**: Replace `module_doc_budget.py`'s unpruned
  `project_root.rglob("CLAUDE.md")` with a pruned `os.walk`, reusing
  `COMMON_VENDORED_BUILD_DIR_NAMES` from `corpus.py`.

### Phase 4: F4 — document the docs-qa system

- [x] ✅ **Task 4.1**: Add `docs_qa_edit`, `docs_qa_commit_gate`,
  `docs_qa_sweep` sections to `docs/guides/HANDLER_REFERENCE.md`, at the
  same depth/format as the `plan_qa` trio, accurate to the shipped code
  (options and defaults sourced from the daemon's config model classes).
- [x] ✅ **Task 4.2**: Add the `documentation:` top-level config block
  (`trees`, `qa.*`) to the same reference doc (documented under
  `docs_qa_edit`, mirroring how `plan_workflow.qa` is documented under
  `plan_qa_edit`).

### Phase 5: N1 + cheap nits

- [ ] ⬜ **Task 5.1**: Fix `skills/docs-qa/SKILL.md` to match the agent
  template's inline-report contract (drop the `untracked/reports/` claim);
  redeploy the dogfood copy so `.claude/skills/docs-qa/` matches.
- [ ] ⬜ **Task 5.2**: Guard the unreadable-file case in the sweep checks
  that read files directly from disk (`module_doc_budget.py`,
  `generated_doc_hand_edit.py`, `at_import_census.py`, `quote_drift.py`,
  `rules_file_shape.py`) — skip with a finding or log rather than aborting
  the whole SessionStart sweep.
- [ ] ⬜ **Task 5.3**: Fix the stale "Until those ship…" phrasing and the
  pre-archive plan path in `CLAUDE/DocumentationStrategy.md`.

### Phase 6: Verification and closeout

- [ ] ⬜ **Task 6.1**: Full QA: `./scripts/qa/llm_qa.py all` green.
- [ ] ⬜ **Task 6.2**: `bin/hooks-daemon restart && bin/hooks-daemon status`
  → RUNNING.
- [ ] ⬜ **Task 6.3**: Re-run `bin/hooks-daemon docs-qa --sweep` and report
  the finding-count delta against the review's 34-advisory baseline.
- [ ] ⬜ **Task 6.4**: Close the plan (Complete, `git mv` to `Completed/`,
  README row move + stats recount, in one commit).

## Success Criteria

- [ ] F1–F4 and N1 fixed, each with a regression test.
- [ ] Cheap nits fixed (unguarded reads, `DocumentationStrategy.md`
  phrasing).
- [ ] `./scripts/qa/llm_qa.py all` fully green.
- [ ] Daemon restarts and reports RUNNING.
- [ ] `docs-qa --sweep` re-run and delta reported.
- [ ] Deferred items (N2, N3, N3b, N5b) recorded as explicit unticked tasks
  above with rationale, not silently dropped.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00287-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone reached at <commit-hash>
