# Plan 00597: plan number helper echo glob inside substitution

**Status**: Complete (2026-11-11)
**Created**: 2026-11-11
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #198

## Overview

`plan_number_helper` (R-PLAN-NUMBER-DISCOVERY) denies a content search inside ONE named
plan when the search runs in a command substitution inside an `echo` (GitHub #198):

`echo "found: $(grep -rl takeover <plan-dir>/00001*/subagent-reports/ | tr '\n' ' ')"`

Rule 3 of `matches()` (the echo/printf glob patterns) searches for
`echo <anything up to a separator> <plan-dir>/<chars>*`. A `$(` is not a separator in
that class, so the pattern runs from `echo` into the grep's own path argument and
reads its `*` as an echoed plan-folder glob. `_without_inside_plan_paths` does not strip
the path first, because `00001*` is a glob, not a full folder name. The same grep
without the echo is allowed, and the `ls` rule already treats a glob carrying two or
more literal digits as naming one plan.

## Goals

- A glob inside a substitution belongs to the command inside it, not to the outer echo.
- A plan-path glob with a literal five-digit prefix (`00001*`) names one plan, for
  rule 3 as it already does for the `ls` rule.
- A real echo discovery scan (`echo <plan-dir>/*`, `printf '%s\n' <plan-dir>/0*`) still
  denies.

## Non-Goals

- Changing what counts as a discovery scan for `ls`, `find` or `sort | tail`.

## Tasks

### Phase 1: Fix (TDD)

- [x] ✅ **Task 1.1**: rule 3 does not read past the start of a substitution; a glob that
  names one plan by its number is not a discovery glob. RED tests both ways.
- [x] ✅ **Task 1.2**: release note 053

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: independent review, merge, main CI green, close #198. The review
  approved with two suggestions. One was a gap this branch opened: arithmetic `$((…))`
  and nested parentheses ended the echo gap early. It was fixed before merge.

## Success Criteria

- [x] The #198 reproduction is allowed; its controls are unchanged
- [x] Every existing R-PLAN-NUMBER-DISCOVERY deny test still denies (271 tests pass)
- [x] Release-bound consequences in the holding area: release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/053-plan-number-helper-echo-glob-inside-substitution.md`

## Follow-ups (not done here)

- `echo "next: $(realpath <plan-dir>/0* | tail -1)"` and
  `echo "$(for d in <plan-dir>/0*; do :; done; echo $d)"` are now allowed. main denied
  them only by accident, through the echo rule; the bare commands are allowed on main
  too. Fix: add `matches()` rules for `realpath`/`readlink -f` over a plan-dir glob and
  for a `for … in <plan-dir>/<glob>` loop, with the same five-digit allowance.

## Delivery & Milestones

- Merged at `fe34001a3`; main CI run 42948971640 green; GitHub #198 closed.
