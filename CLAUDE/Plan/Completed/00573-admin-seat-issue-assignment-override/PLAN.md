# Plan 00573: admin seat issue assignment override

**Status**: Complete
**Created**: 2026-11-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The issue-assignment checks (`AssigneeCheck` in
`utils/github_issue_validity.py`, used by `issue-validity` and the
`github_issue_assignment_guard` handler) block any work tied to an issue
assigned to another account. That is the duplicate-work protection, and it
stays. But it also locks out a repository ADMIN seat. Today the open niggles
ledger (Plan 00474) could not be edited at all because its header names #59,
which was assigned to an inactive non-admin account. Only a human
reassignment by hand freed it.

The owner ruled, in session: a repository admin can always update an issue
assigned to a non-admin, including reassigning it. Keep the duplicate-work
protection. Be pragmatic.

The rule this plan implements:

| Signed-in seat | Issue assigned to   | Result                                                                               |
| -------------- | ------------------- | ------------------------------------------------------------------------------------ |
| non-admin      | another account     | BLOCKING (unchanged)                                                                 |
| admin          | a non-admin account | allowed with an advisory naming the assignee; `--claim` performs a recorded takeover |
| admin          | another admin       | BLOCKING (one admin's claim is respected by another; a human settles it)             |
| admin          | several accounts    | `--claim` reduces them to the admin when every other assignee is a non-admin         |
| any            | nobody / self       | unchanged (claimable / ok)                                                           |

A takeover switches the assignee to the admin and posts one short issue
comment naming the previous assignee, so the hand-over is visible to them.

## Goals

- An admin seat is never blocked by a non-admin's assignment.
- Duplicate work stays visible: the advisory names the current assignee, and a
  takeover leaves a comment.
- Admin status comes from GitHub (`gh api repos/{owner}/{repo}` →
  `permissions.admin` for the viewer; `collaborators/{login}/permission` for an
  assignee), cached per service like the identity. An unknown permission is
  treated as non-admin, the safe direction.

## Non-Goals

- Changing the author whitelist (`approved_issue_authors`).
- Letting a non-admin take over anything.

## Tasks

### Phase 1: Permission-aware assignment checks

- [x] ✅ **Task 1.1**: Failing tests for every row of the table, plus the
  unknown-permission case (falls back to non-admin) and the `gh` lookup
  failing.
- [x] ✅ **Task 1.2**: Implement viewer and assignee permission lookups in
  `IssueValidityService` (one cached call each), and the new outcomes in
  `AssigneeCheck`: an ADVISORY or FIXABLE status with a takeover `FixAction`.
- [x] ✅ **Task 1.3**: The guard allows an admin seat with the advisory
  context. `issue-validity N --claim` performs the takeover: switch the
  assignee, re-read and verify sole assignee, post the comment.
- [x] ✅ **Task 1.4**: Update the runbook (`CLAUDE/development/IssueSdlc.md`
  claim table), the handler guidance, and add a release note.

## Success Criteria

- [x] Tests for each table row fail before the change and pass after it.
- [x] Dogfood: with this seat as admin, a plan whose `**GitHub Issue**` names
  an issue assigned to a non-admin is editable, and the advisory is shown.
  Verified live on issue #155 (see the JOURNAL entry).
- [x] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` records the
  change in the pending-release holding area, with a truth-changes entry,
  because the documented "never claim an issue held by someone else" becomes
  conditional on admin.

## Delivery & Milestones

- Merged to main at `a2b7f27e9` after targeted QA 42/42 (4517 tests). Dogfood
  verified live on issue #155. Ships in the release after v3.73.0 (release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/004-admin-seat-issue-assignment-override.md`).
