# Plan 00570: branch containment remote archive refs

**Status**: In Progress
**Created**: 2026-11-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #166

## Overview

`containment_of` (`core/branch_inventory.py`) decides whether a branch's tip
is held anywhere else by running `for-each-ref --contains` over
`refs/remotes/<remote>` only. A remote can hold a finished branch outside
`refs/heads`, for example under an archive namespace, and the default refspec
never fetches it. Such a branch is reported CONTAINED NOWHERE with the text
"no remote ref holds its commits". That text claims more than was checked. The
sweep then advises `git push -u origin <name>`, which re-creates the archived
branch under `refs/heads` on the remote.

`delete-branch` refuses these branches as "content found nowhere" for a
different reason: its `classify_branch` (`daemon/branch_safety.py`) compares
only against the default branch and the integration-line bases, and never
reads remote refs. So no tool route accepts the remote's own copy as proof. A client with a few dozen archived local branches cannot remove them
through the tools at all, and they hold it over the WIP cap.

This plan follows Plan 00558 (git branch hygiene sweep), whose remote-delete
guard already makes a batched `ls-remote` check (#153). It also extends
Plan 00206 (the deterministic delete proof) and Plan 00249 (the
`delete-branch` crash fix). The remote proof reuses that machinery.

## Goals

- The offline (inventory/hook) message says only what was checked: no
  FETCHED remote-tracking ref holds the commits.
- The explicit CLI commands (`branch-sweep`, `delete-branch`) make one bounded
  `git ls-remote <remote>` call. A remote ref whose sha equals the tip, or
  descends from it, counts as proof that the remote holds the content. The
  command names the ref it relied on.
- The sweep stops advising a push for a tip the remote already holds.
- A network failure or timeout degrades to the offline answer and says so.
  It never counts as proof.

## Non-Goals

- Any network call on a hook path (session start, branch creation guard).
- Fetching or rewriting the client's refspecs.
- The WIP cap's pools (#165, a separate plan).

## Tasks

### Phase 1: Honest offline wording and remote proof

- [ ] ⬜ **Task 1.1**: Failing tests in a scratch-repo fixture (bare remote,
  branch pushed only under an archive namespace): the sweep's wording, the
  absent push advice, `delete-branch` accepting the ls-remote proof, the
  descendant case, and the network-failure fallback.
- [ ] ⬜ **Task 1.2**: Implement the bounded ls-remote check for the CLI
  paths only, and correct the offline wording.
- [ ] ⬜ **Task 1.3**: Update the branch-hygiene docs that state the
  containment rule, plus a release note.

## Success Criteria

- [ ] Tests reproduce the issue's scenario and fail before the fix.
- [ ] No network call is added to any hook handler path (asserted by a test).
- [ ] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` records the
  change in the pending-release holding area.
- [ ] Issue #166 is commented and closed after a verified merge and green CI.

## Delivery & Milestones

- Pending.
