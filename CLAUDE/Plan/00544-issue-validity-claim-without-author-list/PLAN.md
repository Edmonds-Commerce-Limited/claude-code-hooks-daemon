# Plan 00544: issue validity claim without author list

**Status**: In Progress
**Created**: 2026-10-21
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #129

## Overview

`github_issue_assignment_guard` treats an unset `approved_issue_authors` as "author check not applicable", and its deny
text tells you to run `bin/hooks-daemon issue-validity N --claim`. That command refuses to run at all (exit 4) when the
list is unset, so in the configuration the guard calls valid, the only fix the guard names cannot be run.

The CLI refusal exists for `--list-eligible`: autonomous picking with no list would make every author eligible. A
single-issue `--claim N` only assigns the issue the caller already chose, which is the case the guard is lenient about.

Triage evidence: `untracked/scratch/triage-129.md` (session scratch); the verified facts are restated here.

## Goals

- `issue-validity N --claim` works with no author list: the author check reports not applicable, the claim proceeds.
- `--list-eligible` with no author list still refuses loudly (exit 4, no `gh` call).
- The command the guard's deny text names succeeds under the same configuration.

## Non-Goals

- Making `approved_issue_authors` mandatory in config validation (breaks existing configs).
- Changing the guard's deny text or its lenient author check.

## Tasks

### Phase 1: Narrow the refusal

- [x] ✅ **Task 1.1**: Red tests in `tests/unit/daemon/test_issue_validity_cli.py`: claim with no list claims an
  unassigned issue (exit 0, one assign call); `--list-eligible` with no list exits 4 with zero `gh` calls; a set list
  still rejects an unapproved author.
- [x] ✅ **Task 1.2**: Move the not-configured refusal under the `--list-eligible` branch of
  `daemon/issue_validity_cli.py`; the single-issue path prints the author check as not applicable. Update the CLI help
  text and the release note.
- [ ] ⬜ **Task 1.3**: Targeted QA, merge, close #129.

## Success Criteria

- [ ] The three behaviours in Goals are pinned by tests that failed before the change.
- [ ] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` records the behaviour change (the pending-release
  holding area).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00544-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
