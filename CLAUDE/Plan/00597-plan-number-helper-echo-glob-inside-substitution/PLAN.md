# Plan 00597: plan number helper echo glob inside substitution

**Status**: In Progress
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

- [ ] ⬜ **Task 1.1**: rule 3 does not read past the start of a substitution; a glob that
  names one plan by its number is not a discovery glob. RED tests both ways.
- [ ] ⬜ **Task 1.2**: release note

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: independent review, merge, main CI green, close #198

## Success Criteria

- [ ] The #198 reproduction is allowed; its controls are unchanged
- [ ] Every existing R-PLAN-NUMBER-DISCOVERY deny test still denies
- [ ] Release-bound consequences in the holding area: a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`

## Delivery & Milestones

- <!-- delivery commit hash -->
