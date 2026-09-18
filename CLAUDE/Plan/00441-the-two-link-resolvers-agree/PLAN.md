# Plan 00441: the two link resolvers agree

**Status**: In Progress
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

- [ ] ⬜ **Task 1.1**: RED test — a PLAN.md linking to a LIVE plan by a wrong
  path produces a finding that does not claim the target is archived.
- [ ] ⬜ **Task 1.2**: Split the relocation bucket on where the resolved path
  actually sits (active root versus an archive dir, both already known
  from `PlanTreeLayout`) and word each message from that.

### Phase 2: duplicate findings (row (j))

- [ ] ⬜ **Task 2.1**: RED test — a document repeating one dead link yields
  ONE finding, at each of `pointer-resolves`' three stages. The row named
  only the sweep; `_run_edit` and `_run_staged` have the same gap, so a
  blocked write can list the same dead link several times.
- [ ] ⬜ **Task 2.2**: Dedupe the extracted targets once per document,
  preserving first-occurrence order so the reported order is stable.

### Phase 3: the asymmetric fallback (row (l))

- [ ] ⬜ **Task 3.1**: RED test — a repo-root-relative link written in a
  PLAN.md resolves, as the same link does under `pointer-resolves`.
- [ ] ⬜ **Task 3.2**: Give `_resolves_literally` the same fallback, via a
  shared helper rather than a second copy of the rule — a copied resolver
  is what produced this divergence in the first place.

### Phase 4: gate

- [ ] ⬜ **Task 4.1**: `llm_qa format`, then `llm_qa.py all` green with the
  daemon restarted after the last `src/` edit.
- [ ] ⬜ **Task 4.2**: Release note; record rows (j), (k) and (l) on Plan
  00422's `NIGGLES.md`; archive.

## Success Criteria

- [ ] No finding asserts a plan is archived without having established it.
- [ ] Each of the six stage functions across the two checks yields at most one
  finding per distinct link per document.
- [ ] A link that `pointer-resolves` accepts is not reported by
  `plan-link-resolves`, proved by a test that exercises both.
- [ ] `llm_qa.py all` green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00441-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
