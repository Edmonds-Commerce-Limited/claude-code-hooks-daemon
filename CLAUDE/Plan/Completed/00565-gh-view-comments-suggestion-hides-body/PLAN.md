# Plan 00565: gh view comments suggestion hides body

**Status**: Complete
**Created**: 2026-11-05
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #158

## Overview

`gh_issue_comments` and `gh_pr_comments` deny `gh issue view N` / `gh pr view N` without comments, and their REQUIRED
ACTION suggests appending `--comments`. When stdout is not a terminal, which is always the case in an agent's Bash tool
call, `gh ... view N --comments` prints only the comments. The issue or PR body is dropped, and an item with no comments
prints nothing at all (reproduced on `main` for issue #158: 0 lines). An agent following the fix the guard gives
therefore loses the body, which is the opposite of the handlers' purpose.

`gh ... view N --json <fields>,body,comments` returns both. The fix makes that form the suggestion and the documented
route. The block itself is unchanged.

## Goals

- Both handlers' REQUIRED ACTION suggests a command that returns the body AND the comments without a TTY.
- Both handlers' deny reason and `get_claude_md()` guidance say that `--comments` alone shows only comments in
  non-interactive output.
- A command that already has `--json` without `comments` is still corrected by adding `comments` to its field list.

## Non-Goals

- Blocking `--comments` without `--json`. It is still allowed; the guidance warns about it instead.
- Changing what the handlers match or block.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: Failing tests: the suggested command for a bare `gh issue view N` and `gh pr view N` carries
  `--json` with `body` and `comments`; the deny text says `--comments` alone omits the body without a TTY; chained
  commands still get the suggestion on the right segment (`utils/gh_view_comments.suggest_with_comments`).
- [x] ✅ **Task 1.2**: Implement in the shared suggestion helper and both handlers; update `get_claude_md()` and the
  acceptance-test expectations.
- [x] ✅ **Task 1.3**: Release callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`; targeted QA; merge; comment and
  close #158.

## Success Criteria

- [x] Following either handler's suggested command in a non-TTY shell prints the body and the comments (verified live
  on #158 after the merge: body and both comments returned).
- [x] Targeted QA passes on the change (42/42; the two handler files are too broad for the changed-test map, so main's
  CI is their full gate).
- [x] Release-bound consequence recorded in the pending-release holding area: a callout under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the deny message's suggested command changes).

## Delivery & Milestones

- Plan filed from issue #158 triage.
- Red tests `17c3bab80`; fix `3359d918d`; merged to main at `eed7fd934` (release note 001).
