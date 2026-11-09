# Plan 00587: containment follows a cd into compound command bodies

**Status**: In Progress
**Created**: 2026-11-09
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #195

## Overview

`project_containment` (R-WRITE-OUTSIDE-PROJECT-ROOT) resolves a relative write target from the directory the
command's `cd` chain has reached at that step, so `cd sub && echo hi 2>>../f` is judged as `sub/../f` and allowed.
A redirect inside a compound command body loses that directory. Reproduced on `main` at triage:
`cd untracked/scratch/sub195 && for x in a; do echo hi 2>>../loop.err; done` is denied, and the deny names the
target joined to the repository root (`/workspace/../loop.err`), not to the `cd` target. The same redirect outside
the loop is allowed.

The reporter's batch of 40 commands needed a retry with absolute paths, and a sub-agent hit the same false positive
on its own. The rule is right; the directory a compound body runs in is wrong. The `cd` tracking lives in
`_steps_after_a_cd` and `_targets_after_cds` in `handlers/pre_tool_use/project_containment.py`.

Dedupe scout (70 live plans): no live plan covers it. Plan 00464 (commit gates keying on the payload cwd) is a
sibling, not a duplicate. Prior art: Plan 00333 (the out-of-root denial), Plan 00260 (Bash write targets),
Plan 00263 (the POSIX tokeniser).

## Goals

- A relative write target inside a `for`, `while`/`until`, `if`, `{ }` or `( )` body that follows a `cd` in the
  same command is resolved from the `cd` target, exactly as a top-level step is.
- No loosening: a `cd` to a directory outside the project followed by the same compound body is still denied, and
  a target that leaves the project from the `cd` target is still denied.

## Non-Goals

- No change to which commands count as writes, or to the rule's message.
- A `cd` INSIDE a compound body changing the directory for later steps (only the directory a body starts in is in
  scope, unless the existing tracking already models it).

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED tests: each compound shape after a `cd` into a subdirectory with a `../` redirect is
  allowed; each with a `cd` outside the project, or a target escaping the root, is denied
- [ ] ⬜ **Task 1.2**: GREEN in `project_containment.py`'s `cd` tracking
- [ ] ⬜ **Task 1.3**: release-notes callout

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: targeted QA, merge, verify CI, close #195

## Success Criteria

- [ ] The new tests failed before the fix and pass after it, in both directions
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
- [ ] Merged to main with green CI; #195 closed

## Delivery & Milestones

- (pending)
