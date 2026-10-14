# Plan 00520: tdd_enforcement infers the Maven/Gradle source-set layout

**Status**: Complete
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #111

## Overview

`tdd_enforcement` gates Java and Kotlin files under `/src/main/` (the source
directory both TDD strategies declare). None of its inferred resolvers looks at
the sibling test source set, though: the candidates are `tests/`/`Tests/`
next to `src/`, the fallback, the collocated path and `__tests__/`. A
conventionally laid out Maven or Gradle module therefore can never satisfy the
gate. `<module>/src/main/kotlin/<pkg>/X.kt` needs
`<module>/src/test/kotlin/<pkg>/XTest.kt`, and that path is never searched. The
docstring of `_map_src_to_tests_mirror` also claims to cover the "Java
standard layout", which is false.

`test_path_map` with `mirror: true` works around this per project. The default
should infer the standard layout, as it does for the other conventions.

## Goals

- When the source path has `src/main/<anything>/...`, also search
  `src/test/<same>/...` with the strategy's test filename. The resolver is
  additive and language-neutral.
- Correct the mirror resolver's docstring and the handler's guidance on the
  locations checked.

## Non-Goals

- TDD strategies for Scala or Groovy. Their files are not gated today, so they
  cannot be wrongly denied; adding them is a separate feature.
- Changing any existing candidate or its order.

## Tasks

### Phase 1: Resolver

- [x] ✅ **Task 1.1**: Write a failing test reproducing the denial for Kotlin and
  Java under `src/main/<lang>/<pkg>/`, with the test at `src/test/<lang>/<pkg>/`.
- [x] ✅ **Task 1.2**: Add the source-set resolver, anchored like the other
  inferred resolvers (everything before `src`). Search both casings only if
  the existing separate-directory convention does. Cover the edge cases:
  `main` not directly after `src`, and a path with several `src` segments.
- [x] ✅ **Task 1.3**: Fix the docstring and `get_claude_md` guidance, and add
  a release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [x] A Kotlin or Java production Write under `src/main/<lang>/<pkg>/` is
  allowed when the matching test exists under `src/test/<lang>/<pkg>/`, and
  denied when it does not; both cases are proven by tests that failed first
  (`tests/unit/handlers/test_tdd_enforcement.py`, red output in
  [the sub-agent report](subagent-reports/261014-python-developer-sonnet.md)).
- [x] Every candidate path listed before this change is still listed: the new
  resolver only appends, through `_append_unique`.
- [x] The release-bound consequence (a newly inferred layout) is recorded as a
  release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`:
  `057-tdd-enforcement-finds-the-maven-gradle-test-source-set.md`.
- [x] QA green: targeted `llm_qa.py changed` on the combined head da9fff6af
  passed 40/40; `tdd_enforcement.py` is too broad for mapped tests, so CI run
  38523118851 on 24af008e9 ran the whole suite and passed.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00520-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by the issue-sdlc loop from #111.
- Delivered in 1e39a1bcc, merged at da9fff6af; #111 closed.
