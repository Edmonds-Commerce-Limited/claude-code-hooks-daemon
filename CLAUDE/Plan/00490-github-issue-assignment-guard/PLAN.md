# Plan 00490: github issue assignment guard

**Status**: Not Started
**Created**: 2026-10-05
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner asked for a new handler. When a session works on a GitHub issue, that issue must be assigned to the GitHub
account the session is signed in as:

- an issue assigned to nobody may be claimed (assigned to self), and work proceeds;
- an issue already assigned to self may be worked on;
- an issue assigned to someone else, and not to self, must not be worked on.

Sessions do not always work on GitHub issues, so nothing may force every session to have one. The rule applies only
when the work is tied to an issue. The main case is a plan that names its issue in the existing PLAN.md header
convention, `**GitHub Issue**: #N` (see CLAUDE/Plan/CLAUDE.md, "Plan sources").

The owner left the mechanism open ("exactly how you go about that I don't mind"). The design below is the
coordinator's proposal. Items marked **[coordinator call]** are defaults the owner may overturn. This plan follows
the guard-effort pragmatism review (Plan 00483 open question 4): it must not break ordinary sessions, and it stays off
the hot path for anything not tied to an issue.

## Goals

- A session cannot start or continue issue-tied work on an issue assigned only to someone else.
- A session working on an unassigned issue is told to claim it, with the exact command, before work continues.
- Work on an issue assigned to self is never interrupted.
- Work not tied to an issue is never judged, slowed or denied by this handler.

## Non-Goals

- Forcing every session to work on an issue.
- Multi-account `gh` setups. The owner's assumption is one sign-in. With more than one account, or none, the handler
  only advises.
- Judging issues in repositories other than the one the work is in.
- Changing who may be assigned. Org permissions are GitHub's business.

## Design (proposal)

**Identity.** The signed-in login is `gh api user --jq .login`, resolved once per daemon process and cached. If `gh`
is missing, unauthenticated or fails, the handler cannot decide. It emits an advisory and never denies. **\[coordinator
call: fail open, per the pragmatism review's R3 direction\]**

**When work is "tied to an issue".** Detection is cheap and needs no network:

1. A Write/Edit inside a plan folder whose PLAN.md header carries `**GitHub Issue**: #N`.
2. A `git commit` whose message references the issue (`Addresses #N`, the project's non-closing form) while in a plan
   or branch tied to it.
3. The issue-sdlc runbook's own "start work on issue N" step (CLAUDE/development/IssueSdlc.md), which claims
   explicitly.

Everything else exits in `matches()` before any lookup.

**Assignee lookup.** `gh issue view N --json assignees` against the repository's default remote, with a short timeout.
The result is cached per issue for a few minutes, so one plan's many edits cost one lookup. A timeout or error means
advise, not deny.

**Verdicts:**

| Assignees                       | Verdict                                                                   |
| ------------------------------- | ------------------------------------------------------------------------- |
| includes self                   | allow, silently                                                           |
| empty                           | deny; tell the agent to claim with `gh issue edit N --add-assignee @me`   |
| others only                     | deny; the issue belongs to someone else, so do not work on it or claim it |
| lookup failed / identity absent | allow with an advisory naming what could not be checked                   |

**[coordinator call]** The handler does NOT claim the issue itself. Assigning is an outward-facing write to GitHub,
so the agent runs the command and the action is visible in its transcript. The deny reason gives the exact command.
Once the agent has claimed, it retries, the cache is refreshed, and the work goes ahead.

**[coordinator call]** Defaults: enabled in this repository's own config, and off by default in the shipped template
for client projects, until it has run here for a while.

## Tasks

### Phase 1: Confirm the ground

- [ ] ⬜ **Task 1.1**: Inventory where the `**GitHub Issue**: #N` header appears today (live and archived plans), and
  how issue-sdlc and agents start issue work. Confirm the detection points above, or adjust them.
- [ ] ⬜ **Task 1.2**: Probe `gh` behaviour here: `gh api user`, `gh issue view --json assignees`, and
  `gh issue edit --add-assignee @me`, using a read-only probe of an existing issue (no assignment changes made
  for the probe). Also probe the failure shapes: no auth, no network, an issue that does not exist.

### Phase 2: The handler (TDD)

- [ ] ⬜ **Task 2.1**: Failing tests first, for each row of the verdict table and the "not tied to an issue" fast path.
  Use a faked `gh` runner; there is no network in the tests.
- [ ] ⬜ **Task 2.2**: Implement the PreToolUse handler, with identity and assignee caches and timeouts. Detection
  stays in `matches()`, with no I/O for untied work.
- [ ] ⬜ **Task 2.3**: Add the handler's `get_acceptance_tests()`, its CLAUDE.md guidance, its config entries
  (enabled here, off in the client template) and its rule IDs.
- [ ] ⬜ **Task 2.4**: Add a regression check that a corpus of ordinary non-issue commands and edits stays allowed and
  makes no `gh` call.

### Phase 3: Workflow and docs

- [ ] ⬜ **Task 3.1**: Add a claim step to the issue-sdlc runbook: check the assignees, claim when unassigned, stop when
  the issue belongs to someone else.
- [ ] ⬜ **Task 3.2**: Add a release note under CLAUDE/UPGRADES/UNRELEASED/release-notes/ and the handler reference
  entry.

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Do a live dogfood check in this repository after a daemon restart:
  - an untied edit is silent;
  - an edit in a plan tied to an issue assigned to self is allowed;
  - an unassigned issue is denied with the claim command.

## Open questions for the owner

1. Should the handler claim unassigned issues itself rather than tell the agent to? The default is to tell, because
   assignment publishes to GitHub.
2. Should it be on by default for client projects? The default is off in the client template and on here.
3. When `gh` cannot answer (offline, not signed in, several accounts), should it advise or deny? The default is
   advise, per the pragmatism review.

## Success Criteria

- [ ] All verdict-table rows are pinned by tests, and the not-tied path makes no `gh` call and adds no measurable
  latency.
- [ ] The issue-sdlc runbook claims before working and stops on someone else's issue.
- [ ] The live dogfood check (Task 4.1) passes after a daemon restart.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
