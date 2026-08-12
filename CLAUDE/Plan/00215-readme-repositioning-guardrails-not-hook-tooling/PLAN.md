# Plan 00215: readme repositioning guardrails not hook tooling

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A cold-reader review of the README (against v3.51.0) found one structural
problem and several factual errors. The structural problem: the README answers
*"why a daemon?"* at length and never answers *"why guardrails?"*. `## Why Use This?` is ~400 words entirely about iteration speed for hook authors — true,
worth keeping, and the answer to the **second** question. The first question is
why an autonomous agent needs blocking rules at all, and the README never puts
it in a sentence. The word "safety" appears exactly once, as a priority-band
label.

The consequence is that a reader with ninety seconds files the project under
developer ergonomics rather than agent safety infrastructure — which is what the
code actually is.

Two factual errors compound it. The README says a project gets "just five Claude
Code hooks — one per event type" while stating "15 event types" three sections
later, and there are 31 forwarder scripts in `.claude/hooks/`. And the test badge
(`10800+`) is pytest's collected count, correct but unverifiable by a reader who
greps `def test_` and finds ~9,888, concluding the badge is inflated.

## Context & Background

- `REQUESTS.md` — the full change request as received, kept as a supporting
  document (Plan 00211's EXTRACT remedy) rather than inlined here.

## Goals

- Make the README state, above the fold, what the project is FOR — deterministic
  guardrails evaluated on every tool call before it runs.
- Reorder so a first-time reader meets the purpose before the install commands.
- Correct the two factual errors, and add a verifiable figure alongside the test
  badge rather than a contestable one.

## Non-Goals

- **Do NOT invent an origin story.** Item 5 of the request asks for one factual
  sentence about the incident that started the project, and explicitly gates it:
  *"Needs the real detail — do not draft this without it. Invented specifics
  would be worse than nothing."* RESOLVED: the maintainer supplied the real
  detail — an agent ran `git branch -D` once and days of work went with it —
  and that sentence is now in `README.md` at the end of "What this solves".
  The gate held: nothing was drafted until the fact arrived.
- Do NOT touch the generated handler counts (`92 production handlers across 15 event types`) — the release process owns those.
- Do NOT rewrite `## Project-Level Handlers`, `## Writing Custom Handlers`,
  `## Configuration`, `## Git Integration` or `## Troubleshooting`; the review
  found them accurate and well-scoped.
- Do NOT carry the request's closing "Not for export" section into this
  repository in any form — it concerns a different project's positioning.

## Tasks

### Phase 1: Structural repositioning

- [x] ✅ **Task 1.1**: Replace the strapline with a claim rather than a category
- [x] ✅ **Task 1.2**: Add a `## What this solves` section stating the guardrail
  case and the determinism property (a handler returns allow/deny; it is not a
  prompt and not a judgement the model makes about its own behaviour)
- [x] ✅ **Task 1.3**: Reorder to strapline → What this solves → Why a daemon →
  What's Built In → Installation & Updates → rest unchanged
- [x] ✅ **Task 1.4**: Retitle `## Why Use This?` to `## Why a daemon rather than plain hooks`, keeping all five sub-headings
- [x] ✅ **Task 1.5**: Promote `## Deterministic vs Agent-Based Hooks` to sit
  directly after `## What's Built In`

### Phase 2: Factual corrections (each must be re-measured, not copied)

- [x] ✅ **Task 2.1**: Replace "just five Claude Code hooks — one per event type"
  with "one lightweight forwarder per event type"; verify the forwarder count in
  `.claude/hooks/` first. Re-measured: 31 forwarder scripts (32 entries minus the
  `handlers/` support subdirectory) — matches the request; the "just five" text
  was already gone from the live file, so this was a wording tightening
- [x] ✅ **Task 2.2**: Add the source-to-test line ratio beside the test badge,
  measuring both figures rather than trusting the request's numbers. Re-measured
  via `find … -exec wc -l`: 69,419 source lines / 157,974 test lines = 2.3× —
  both figures differ from the request's (63,509 / 145,073) but the ratio
  matches almost exactly; trusted my own measurement
- [x] ✅ **Task 2.3**: Reconcile the priority bands — `## What's Built In` lists
  five categories, `## Writing Custom Handlers` lists six; add the missing band
  or drop it. Re-measured: actually 4 vs 5 (not 5 vs 6) before this change. Added
  a `### Advisory` category to `## What's Built In` (british_english,
  daemon_docs_guard) without touching `## Writing Custom Handlers`, which is on
  the do-not-rewrite list
- [x] ✅ **Task 2.4**: Move `Requirements` (Python version, OS support) up, or
  surface those two facts in the badge row. Chose the badge-row option: added a
  Platform badge (Python version was already badged)
- [x] ✅ **Task 2.5**: Add a one-line maintainer credit with a link near the top.
  Linked to the GitHub org already referenced elsewhere in the file
  (`Edmonds-Commerce-Limited`) rather than an unverified external URL

### Phase 3: Verification

- [x] ✅ **Task 3.1**: Confirm every retained claim is independently verified
  against the repository, not carried over from the request document
- [x] ✅ **Task 3.2**: Run QA — `validate_instruction_content` and `doc_truth`
  both police README content. `./scripts/qa/llm_qa.py all` (in-worktree, via a
  borrowed shared venv) → 17/20 PASSED, 3/20 FAILED. `doc_truth: 0 violations`
  (the check that governs README content) and `british_english: 0 violations`
  both passed cleanly. The 3 failures are worktree/shared-venv artefacts, not
  README regressions: `tests` reported 11805 passed/0 failed/15 skipped but a
  non-zero exit + implausible 4.2% coverage (coverage data corrupted by
  concurrent sibling-agent pytest runs sharing the borrowed venv);
  `smoke_test` needs a live daemon socket that only exists for the real
  project root, which a worktree cannot provide; `canonical_callers` did not
  run. This in-worktree run is informational only — the coordinator's
  authoritative gate is the full suite re-run on the merged tree against the
  real project root

## Success Criteria

- [ ] A reader learns what the project is FOR before meeting an install command
- [ ] No factual claim in the README contradicts another
- [ ] Every number in the README was re-measured during this plan
- [ ] The origin-story line is either supplied by the maintainer or absent — not
  invented
- [ ] QA passes and the daemon restarts cleanly

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00215-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Change request received and filed as a tracked plan
