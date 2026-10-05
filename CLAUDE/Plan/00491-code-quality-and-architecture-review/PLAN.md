# Plan 00491: code quality and architecture review

**Status**: Not Started
**Created**: 2026-10-05
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The project owner ruled on 2026-10-05 (B5, see
[OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md)) that the module-size
question in niggle N314 is not answered by a size gate alone. The owner asked for a general code-quality and
architecture review covering module size, duplication (DRY), an architecture overview and code quality, perhaps followed
by a refactoring effort.

`scripts/qa/check_module_length.py` already reports 26 modules over 1,000 lines out of 672 under `src/`. The largest,
`subagent_full_qa_blocker.py`, reached 5,301 lines unnoticed; its split is tracked in Plan 00485. This plan looks at the
whole code base, then chooses refactors with the owner.

N314 (the size gate and its exception list) folds into this plan. The 00483 R5 effort budget (one open branch, at most
two review rounds, no net growth in lines, a per-command latency limit, the size check as a gate on the three area
modules) applies to the guard area throughout.

## Goals

- A prioritised, evidence-backed report on module size, duplication, layering, dead code and overall architecture.
- A refactoring list chosen from that report together with the owner.
- A decision on how module size is bounded in QA, reached inside the review rather than as a stand-alone allowlist.

## Non-Goals

- No code change in Phase 1: the analysis is read-only.
- No refactor without the owner choosing it from the report.
- No new guard behaviour; the guard area follows the 00483 rulings.
- Not a re-do of Plan 00485, which keeps its own scope.

## Tasks

### Phase 1: Read-only analysis

- [ ] ⬜ **Task 1.1**: Measure module sizes under `src/` and `scripts/`: the 26 modules over 1,000 lines, the
  distribution, and which are growing (use git history).
- [ ] ⬜ **Task 1.2**: Find duplication and DRY hotspots: repeated parsers, repeated handler boilerplate, copied helpers
  across handlers, near-identical tests.
- [ ] ⬜ **Task 1.3**: Write an architecture overview: packages, the dependency direction between them, and layering
  violations (imports that cross a layer the wrong way).
- [ ] ⬜ **Task 1.4**: Find dead code: unreferenced functions, constants, options and handlers, with evidence for each.
- [ ] ⬜ **Task 1.5**: Assess code quality: complexity hotspots, error handling, typing gaps, and test seams that make
  modules hard to change.
- [ ] ⬜ **Task 1.6**: Write the report to a supporting document in this folder, with findings ranked by value and risk,
  and a recommendation on bounding module size (N314). Sub-agent reports go under `subagent-reports/`.

### Phase 2: Refactoring, chosen with the owner

- [ ] ⬜ **Task 2.1**: Put the ranked findings to the owner and record which are taken, deferred or dropped.
- [ ] ⬜ **Task 2.2**: Turn each taken finding into a task here (or a sequenced plan when it is large), at most 3
  branches open at once (Plan 00475). Each refactor is behaviour-preserving, with tests green before and after.
- [ ] ⬜ **Task 2.3**: Apply the module-size decision from the report (gate, exception list, or neither) and close N314.

## Success Criteria

- [ ] The report exists with prioritised findings, each citing file and line evidence.
- [ ] The owner has ruled on every finding: taken, deferred or dropped.
- [ ] Every taken refactor has merged with targeted QA green, or has its own plan.
- [ ] N314 is closed with the owner's chosen size policy recorded.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00491-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan created from owner ruling B5.
