# Plan 00441: the two link resolvers agree

**Status**: Complete
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

Two checks resolve markdown links in this repository: docs QA's
`pointer-resolves` and plan QA's `plan-link-resolves`. They share a resolver
(`PlanLinkResolver`) and a target extractor, and they were written months
apart, so they answer the same question three different ways. Rows (j), (k)
and (l) of the ledger file them as three niggles; they are one cluster in two
files, which is why they are one plan.

The one with teeth is (k). `PlanLinkResolver._index_folders` indexes the
active plan root FIRST and then each archive, first match wins, with a comment
saying so: "the LIVE plan is the better answer to 'where is plan N'". So the
resolver deliberately returns live plans — while the finding built from it
says, unconditionally, "PLAN.md links to plan(s) that have been archived". An
author who mistypes a `../` depth for a plan that is very much alive is sent
to look in `Completed/`, where it is not.

(j) and (l) are quieter. `pointer_resolves` emits one finding per link
OCCURRENCE, so a document repeating a dead link prints the same finding
several times, while the plan-QA twin dedupes and emits one per document. And
`plan_link_resolves._resolves_literally` tries only relative-to-the-file,
while `pointer_resolves` also falls back to repo-root-relative — so a link
this project's docs write routinely resolves under one check and is reported
as needing a repoint under the other.

This is niggle N5 rows (j), (k) and (l) of the ledger in Plan 00422.

## Goals

- A relocation finding names where the target actually IS, not where the
  message's author assumed it would be.
- One finding per link per document, in every stage of both checks.
- The two checks resolve a literal link by the same rules.

## Non-Goals

- No merging of the two checks into one. They differ in scope, severity
  policy and stage set for reasons each documents; the complaint is that they
  disagree on shared mechanics, not that they both exist.
- No change to `PlanLinkResolver`'s active-root-first ordering — it is right,
  and (k) is the message failing to keep up with it.

## Tasks

### Phase 1: the wrong word (row (k))

- [x] ✅ **Task 1.1**: RED test — a PLAN.md linking to a LIVE plan by a wrong
  path produces a finding that does not claim the target is archived. Shipped
  with two controls that passed from the start: the remediation must still name
  the live path, and a genuinely archived target must still be called archived.
- [x] ✅ **Task 1.2**: Split the relocation bucket on where the resolved path
  actually sits. `PlanTreeLayout.is_archived` already existed and is the right
  question, so no new helper — the defect was that nothing asked it.

### Phase 2: duplicate findings (row (j))

- [x] ✅ **Task 2.1**: RED test — a document repeating one dead link yields
  ONE finding, at each of `pointer-resolves`' three stages. The row named
  only the sweep; `_run_edit` and `_run_staged` have the same gap, so a
  blocked write can list the same dead link several times. All three were
  observed RED at `3 == 1`, with two controls green throughout: two DIFFERENT
  dead links still yield two findings, and the surviving finding still names
  the link.
- [x] ✅ **Task 2.2**: Dedupe the extracted targets once per document,
  preserving first-occurrence order so the reported order is stable.
  `dict.fromkeys` rather than a set, for exactly that reason.

### Phase 3: the asymmetric fallback (row (l))

- [x] ✅ **Task 3.1**: RED test — a repo-root-relative link written in a
  PLAN.md resolves, as the same link does under `pointer-resolves`. Two
  controls green throughout: a relative-to-the-file link still resolves, and a
  link resolving under neither is still reported.
- [x] ✅ **Task 3.2**: `utils/link_resolution.py` holds the rule; both checks
  delegate. Docs QA's copy was DELETED rather than left in place, so there is
  no second definition to drift — `_exists_within` and `_strip_fragment` went
  with it. 13 direct tests, including the two that prove it is not an
  existence oracle for host paths.

### Phase 4: gate

- [x] ✅ **Task 4.1**: `llm_qa format`, then `llm_qa.py all` green with the
  daemon restarted after the last `src/` edit — 35/35, no failed gates.
- [x] ✅ **Task 4.2**: Release note; record rows (j), (k) and (l) on Plan
  00422's `NIGGLES.md`; archive.

## Success Criteria

- [x] ✅ No finding asserts a plan is archived without having established it,
  via `PlanTreeLayout.is_archived` on the path the resolver actually returned.
- [x] ✅ Each stage across the two checks yields at most one finding per
  distinct link per document — proved at all three `pointer-resolves` stages,
  each seen RED at `3 == 1`.
- [x] ✅ A link that `pointer-resolves` accepts is not reported by
  `plan-link-resolves`, proved by a test that exercises both.
- [x] ✅ `llm_qa.py all` green, 35/35.
- [x] ✅ Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/18-the-two-link-checks-now-agree.md`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00441-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed with the three rows verified at code level, at `0d452588`.
- Delivered at `c607a6d6` — all three phases, the shared resolver and the
  release note.
- Archived in the following commit, with the README row and statistics.
