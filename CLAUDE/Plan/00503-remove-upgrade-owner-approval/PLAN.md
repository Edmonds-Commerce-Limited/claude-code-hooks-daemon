# Plan 00503: remove upgrade owner approval

**Status**: In Progress
**Created**: 2026-10-11
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #112

## Overview

Plan 00376 built a pre-deploy upgrade gate with two tiers. The reading
confirmation (exit 3) stops until the upgrade is re-run with the digest of
what it listed. The owner approval (exit 4) stops a breaking upgrade until
the project owner runs `hooks-daemon approve-upgrade` in their own terminal.
The `upgrade_approval_guard` handler stops an agent from recording that
approval.

The owner asked on 2026-10-11 for the approval tier to be removed. It adds busy work
and no safety, and an older installed daemon has no `approve-upgrade` verb,
so a project gets stuck behind a long pipeline command just to say yes.
The project's threat model is careless agents, not hostile ones, so a guard
against forging the approval defends against nothing in scope.

## Goals

- No upgrade stops for owner approval: exit 4, the `upgrade-approvals/`
  markers and the `approve-upgrade` verb are gone.
- The `upgrade_approval_guard` handler and its two rules are gone, and a
  project config that still names it keeps validating.
- The reading confirmation (exit 3) still works, and lists what used to need
  approval (a MAJOR bump, a breaking manifest, a critical task, an unreadable
  installed version) prominently.
- A large jump (a MAJOR boundary, or many minor releases) prints advice to
  upgrade in phases through an intermediate release. Advice only.

## Non-Goals

- Changing the reading confirmation itself.
- Editing past release notes, which are history.

## Tasks

### Phase 1: Implement

- [ ] 🔄 **Task 1.1**: Remove the approval tier from the gate and the CLI
  (sub-agent, worktree `worktree-rm-upg-approval`).
- [ ] 🔄 **Task 1.2**: Delete `upgrade_approval_guard` with its registrations
  and tests; keep an old config naming it valid.
- [ ] 🔄 **Task 1.3**: Add the phased-upgrade advisory (TDD).
- [ ] 🔄 **Task 1.4**: Establish whether an upgrade from an older install runs
  the gate from the target's code, and document the route for one that does not.
- [ ] 🔄 **Task 1.5**: Docs, release note, config-changes and truth-changes
  entries.

### Phase 2: Land

- [ ] ⬜ **Task 2.1**: Review, coordinator QA, merge.
- [ ] ⬜ **Task 2.2**: Plan 00477 Task 5.3 asks the owner how provisioning
  should satisfy the approval rule; mark it moot there.

## Success Criteria

- [ ] No code path exits 4 or reads an approval marker; `approve-upgrade` is
  not a CLI verb.
- [ ] `upgrade_approval_guard` is absent from source, config and generated
  guidance, and a config still naming it validates.
- [ ] The phasing advisory has tests and never changes the exit code.
- [ ] The release-bound consequences (the removed handler and verb) are in
  the pending-release holding area: a release note and the manifest entries.

## Delivery & Milestones

- Issue #112 filed and claimed.
