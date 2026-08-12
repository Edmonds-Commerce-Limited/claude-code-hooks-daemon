# Plan 00211: plan size guidance missing extract remedy

**Status**: Complete
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A field report (`REPORT.md`) found that the plan-size advisory
(`plan-doc-size`) offers exactly TWO remedies for an oversized `PLAN.md` —
relocate narrative into `JOURNAL/`, or split the plan — but the most common
cause of an oversized plan is content that is durable, detailed and CURRENT
(research output, decisions and their reasoning, evidence tables, drafts).
That is not history (so not `JOURNAL/`) and not task tree (so not a split),
so it stays in `PLAN.md` and inflates it. The missing third remedy is
EXTRACT INTO A NAMED SUPPORTING DOCUMENT in the plan folder — a concept this
project's own internal `CLAUDE/PlanWorkflow.md` already documents, but which
never reached the client-facing deployed guidance
(`install/templates/PlanJournalling.md`, the injected `plan_workflow`
CLAUDE.md section, or the `plan-doc-size` remediation text itself).

This plan adds the third remedy everywhere it is currently missing, teaches
`plan-shrink-without-journal` to recognise extraction (not just journalling)
as a legitimate relocation, adds a folder-shape hint to the advisory, and
closes the DRY gap that let the two-remedy text drift by extracting a single
source-of-truth constant that all three surfaces render from. It also adds a
doc-parity regression guard (DBF) so this specific class of drift — a
concept documented internally but never ported to client-facing docs —
cannot silently recur.

## Goals

- Add EXTRACT as the first-listed remedy in `plan_doc_size.py`'s `_REMEDY`
- Make the `plan_workflow` guidance table three-column (`PLAN.md` /
  `SOME-DOC.md` / `JOURNAL/`)
- Add a folder-shape hint (suggestion, never assertion) to the advisory
- Teach `plan-shrink-without-journal` to accept a staged supporting doc as
  evidence of relocation, exactly as it accepts a journal entry
- Extract ONE source-of-truth constant for the remedy wording, consumed by
  all three surfaces (`plan_doc_size.py`, `plan_qa_edit.py`,
  `plan_workflow.py`), with a test that fails on divergence
- Port the supporting-docs concept to the deployed client template
  (`install/templates/PlanJournalling.md`) and the internal dogfood copy
  (`CLAUDE/PlanJournalling.md`, kept byte-identical per the installer's
  "client-owned, never overwritten" seeding contract)
- Add a DBF doc-parity regression guard between `CLAUDE/PlanWorkflow.md`
  (this project's own internal planning conventions) and the client-facing
  docs, so this drift class cannot silently recur

## Non-Goals

- Not implementing the "repeat-firing advisory" generalisation the report
  raises as a closing lesson — recorded as a Technical Decision / follow-up
  candidate below, not built here
- Not changing the numeric size tiers (18,000/25,000/35,000 bytes) — only
  the remedy wording and the shrink-check detection logic
- Not touching `docs/PLAN_SYSTEM.md` / `docs/guides/HANDLER_REFERENCE.md`
  content depth beyond keeping the remedy count consistent (best-effort,
  not the core of this plan)

## Tasks

### Phase 1: Single source of truth for remedy wording

- [x] ✅ **Task 1.1**: TDD `plan_qa/remedy.py` — `REMEDIES` tuple (EXTRACT
  first, then RELOCATE, then SPLIT), `remedy_sentence()` and
  `remedy_markdown_list()` renderers
- [x] ✅ **Task 1.2**: Wire `plan_doc_size.py`'s `_REMEDY` from
  `remedy_sentence()`
- [x] ✅ **Task 1.3**: Wire `plan_qa_edit.py`'s `get_claude_md()` bullet from
  `remedy_sentence()`
- [x] ✅ **Task 1.4**: Wire `plan_workflow.py`'s `get_claude_md()` remedy
  list from `remedy_markdown_list()`, and widen the contract table to
  three columns (`PLAN.md` / `SOME-DOC.md` / `JOURNAL/`)
- [x] ✅ **Task 1.5**: Cross-surface DRY test — every surface's rendered
  text contains the canonical rendering; fails on divergence

### Phase 2: Folder-shape hint

- [x] ✅ **Task 2.1**: TDD `_folder_has_supporting_docs()` helper in
  `plan_doc_size.py` and the `_FOLDER_SHAPE_HINT` suggestion text
  (never an assertion — honours the report's 00001 counter-example)
- [x] ✅ **Task 2.2**: Wire the hint into `_run()`, appended to
  `remediation` whenever a Finding fires and the folder has no
  supporting docs

### Phase 3: Teach plan-shrink-without-journal about extraction

- [x] ✅ **Task 3.1**: RED — failing test: a commit that shrinks PLAN.md by
  \>2,000 bytes while staging a new supporting `.md` (no journal entry)
  must be SILENT, not flagged
- [x] ✅ **Task 3.2**: GREEN — add `has_staged_supporting_doc()` to
  `plan_qa/checks/common.py`; `plan_shrink_without_journal.py` accepts
  it alongside `has_staged_journal_entry()`
- [x] ✅ **Task 3.3**: Update the finding's remediation text to mention the
  extraction alternative

### Phase 4: Ship the concept to clients + DBF guard

- [x] ✅ **Task 4.1**: Port the supporting-docs structure into
  `install/templates/PlanJournalling.md` (two-remedy -> three-remedy,
  layout section mentions supporting docs) and sync
  `CLAUDE/PlanJournalling.md` byte-identically (installer never
  overwrites the deployed copy, so both must be edited)
- [x] ✅ **Task 4.2**: Doc-parity regression test — structural concepts
  (`supporting`, `assets/`) present in `CLAUDE/PlanWorkflow.md` must
  also be present in the deployed template and the injected
  `plan_workflow` CLAUDE.md guidance
- [x] ✅ **Task 4.3**: Best-effort consistency pass over
  `docs/PLAN_SYSTEM.md` / `docs/guides/HANDLER_REFERENCE.md` remedy
  mentions

### Phase 5: QA and verification

- [x] ✅ **Task 5.1**: `./scripts/qa/llm_qa.py all` reaches 18/20 PASSED.
  The 2 remaining failures are OUT OF SCOPE, not regressions from this
  plan: (a) 5 pre-existing `tests` failures all trace to Plan 00208's
  `CommentChangelogHandler`/`CommentSizeHandler` work, already committed
  on the base branch before this plan started (confirmed by
  `git merge-base --is-ancestor` on the introducing commits); (b)
  `smoke_test` requires a live daemon socket, which cannot exist for a
  worktree project root. Fixed two REAL issues this run surfaced that
  WERE mine: 3 files needing `black` reformatting, and this plan's own
  README index row exceeding the 500-char line-length contract.
- [x] ✅ **Task 5.2**: Daemon-restart verification — DONE post-merge against
  the real project root, which is where it always had to happen. The
  worktree correctly reported it OUTSTANDING rather than claiming it.
  Evidence: daemon restarted to `RUNNING` with no load errors in the log;
  a live `PreToolUse`/`Write` probe of an over-threshold `PLAN.md` returned
  the three-remedy text with EXTRACT listed FIRST, followed by the
  folder-shape hint and its "suggestion based on folder shape, not a
  diagnosis" caveat; `plan-qa --sweep` reports no structural drift; and the
  full suite reaches **20/20** on the merged tree, so the 2 checks the
  worktree could not satisfy were indeed environmental.

## Technical Decisions

### Decision 1: DRY enforcement mechanism for the remedy text

**Context**: the two-remedy wording was hand-copied into three surfaces
(`plan_doc_size.py`, `plan_qa_edit.py`, `plan_workflow.py`) and had already
drifted (missing EXTRACT). Three independent hand-edits would just recreate
the same failure mode.

**Decision**: extract a single `plan_qa/remedy.py` module holding the
`REMEDIES` data and two renderers (`remedy_sentence()` for prose contexts,
`remedy_markdown_list()` for CLAUDE.md numbered-list contexts). All three
surfaces import and render from it — never hand-write the wording again. A
cross-surface test asserts each surface's text contains the canonical
rendering, so a future hand-rewrite fails CI instead of silently drifting.

### Decision 2: DBF guard scope

**Context**: the sharpest finding in the report is that a concept
(supporting docs) has lived in this project's own internal
`CLAUDE/PlanWorkflow.md` and never reached the client-facing deployed docs.
Fixing the wording once does not stop a *different* concept drifting the
same way in the future.

**Decision**: add a targeted doc-parity test — not a generic "diff all
docs" tool (out of scope, hard NLP problem) — that pins the specific
concepts this defect was about (`supporting`, `assets/`) and asserts they
appear in both the internal doc and the deployed template / injected
guidance. This is an honest, narrow instantiation of DBF for this defect
class; it will not catch an unrelated future concept drift, only a
regression of this one.

### Decision 3 (deferred): repeat-firing advisory as a signal

**Context**: the report's closing lesson — an advisory that fires
repeatedly without being resolved is itself a signal ("this has fired N
times; re-diagnose rather than reapplying") — generalises past
`plan-doc-size` to any advisory handler.

**Decision**: recorded here, not implemented. It needs per-check,
per-plan firing-history storage that no current check has, and is a
cross-cutting concern (advisory infrastructure, not this handler). A
follow-up plan is the right vehicle once a concrete design for that
storage exists.

## Success Criteria

- [x] `_REMEDY` / `get_claude_md()` on all three surfaces list EXTRACT
  first, RELOCATE second, SPLIT third, rendered from one shared module
- [x] Cross-surface DRY test fails if any surface's wording diverges from
  `plan_qa/remedy.py`
- [x] `plan-doc-size` finding remediation includes a folder-shape hint
  (suggestion wording only) when the plan folder has no supporting docs
- [x] `plan-shrink-without-journal` is silent when a shrink is accompanied
  by a staged new supporting `.md`, with no journal entry required
- [x] `install/templates/PlanJournalling.md` and `CLAUDE/PlanJournalling.md`
  are byte-identical and both document the three-remedy world and
  supporting docs
- [x] A DBF doc-parity test fails today (before the fix, confirmed via
  `git show` on the pre-fix commit) and passes after
- [x] `./scripts/qa/llm_qa.py all` reaches 18/20 PASSED in the worktree — the
  2 remaining were confirmed out-of-scope (see Task 5.1) and both pass on the
  merged tree, which reaches **20/20**
- [x] Daemon-restart verification reported as OUTSTANDING rather than claimed
  while in the worktree, then actually performed post-merge against the real
  project root (see Task 5.2)

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00211-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Implementation complete (Phases 1-4) at `4ff56760`..`06442044`
- QA green (18/20, 2 confirmed out-of-scope) at `23f86830`
- Daemon-restart verification and live CLI probe OUTSTANDING — see
  JOURNAL for detail; this plan stays In Progress until a session with
  the real project root completes them
