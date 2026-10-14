# Plan 00522: the pytest text report reads pytest's final summary line

**Status**: In Progress
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #115

## Overview

`qa/pytest_text_report.parse_pytest_text_output` (built by Plan 00226) takes
each of the passed, failed, skipped and error counts from its first match
anywhere in pytest's console output. When a failure message embeds the summary
of a nested pytest run, as the integration test that runs pytest on a copy of
the tree does, that nested summary supplies some or all of the totals. On a
real sharded run this recorded a total of 235 where pytest's own line said
6,553, and 1 failed where 6 had. The shard still read as failed only because the
exit code is combined in afterwards.

Reproduced on `main`: for `"E 1 failed, 3 passed in 2.00s\n===== 6 failed, 100 passed, 5 skipped in 60.00s =====\n"` the parser returns total 9.

## Goals

- Every count comes from pytest's own final summary line (the last
  `=`-delimited line that carries counts), and from that one line only.
- An output with no such line keeps today's behaviour.

## Non-Goals

- Making pytest-json-report a declared dependency.
- Changing how the exit code is combined into the verdict, or the failed-test
  list extraction (unless it shares the defect; if so, report it).

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: RED: tests for the reported shape, for a nested summary
  that carries only some of the counts, for `error`/`errors` and `xfailed`
  wording on the final line, and for an output with no final line.
- [x] ✅ **Task 1.2**: GREEN: read the final summary line, all counts from it.
- [x] ✅ **Task 1.3**: Release note if the parser ships to client installs;
  otherwise state why none is needed.

## Success Criteria

- [ ] A nested summary earlier in the output never changes any count, proven
  by tests that failed first.
- [ ] Release-bound consequences recorded in `CLAUDE/UPGRADES/UNRELEASED/`, or
  the plan states it has none and why.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00522-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by the issue-sdlc loop from #115.
