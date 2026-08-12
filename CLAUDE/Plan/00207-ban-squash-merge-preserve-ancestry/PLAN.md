# Plan 00207: ban squash merge preserve ancestry

**Status**: Not Started
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

> **Scope correction.** This plan began as "ban squash merge". Measurement
> showed the defect is not specific to squashing: a **rebase merge** severs
> ancestry identically, and GitHub offers it as one of three merge buttons. The
> policy is therefore **mandate ancestry-preserving merges**, of which banning
> the squash merge is one half.

A squash merge collapses N commits into one new commit on the target, and a
rebase merge replays them as new commits with new shas. In both cases the
branch's original commits never become ancestors of that target, so
`git branch -d` — the safe, battle-tested delete — refuses the branch
permanently, even though its content is fully upstream.

The consequence is a downgrade in the tooling you are allowed to trust.
`git branch -d` is decades old and independently verifies the merge itself;
`hooks-daemon delete-branch` (Plan 00206) is days old and verifies it with our
own code. Plan 00206 exists to cover the cases `-d` genuinely cannot reach — a
history rewrite, principally — and a squash merge manufactures that same
condition **voluntarily, on every merge**, for no benefit to the delete path.

This plan blocks the squash merge so ancestry survives and `-d` stays usable.
The argument is deliberately narrow: not "squash merges are bad", but "a squash
merge permanently forfeits the safest branch-deletion check available". The
familiar history-granularity costs — `git bisect` resolution, `git blame`
precision, the per-commit rationale — are real and reinforce it, but they are
not the load-bearing reason.

## Goals

- Block every integration style that severs ancestry — `git merge --squash`,
  `gh pr merge --squash` and `gh pr merge --rebase` — by default, with an
  escape hatch, following the `git_stash` precedent already in this codebase.
- Reduce the situations requiring a force delete to the two that no policy can
  remove: truly abandoned work, and history rewrites.
- Make the block message explain the ancestry consequence rather than asserting
  a style preference, so the guidance survives disagreement about style.
- Keep the handler configurable (`mode: warn`) and disableable, because
  squash-only is a *mandated* workflow in many organisations and a hard,
  unconditional ban would fight their platform settings.

## Non-Goals

- No attempt to block squash merges performed in a web UI. The daemon sees tool
  calls, not GitHub button clicks; a handler that implies otherwise would be
  claiming coverage it does not have — the exact defect corrected in v3.52.0.
- No change to `delete-branch`. It already handles squash-merged branches
  correctly via `content-preserved`, verified in Plan 00206.
- No opinion on rebasing as a *local* practice. Rebasing a feature branch onto
  an updated `main` before merging is fine and preserves ancestry; it is the
  rebase *merge* — replaying onto the target and fast-forwarding — that severs
  it.

## Context & Background

Measured, not assumed. Each integration style was applied to a two-commit
branch in a throwaway repository, then `git branch -d` attempted:

| Integration style        | Safe `-d` afterwards | Avoidable by policy?           |
| ------------------------ | -------------------- | ------------------------------ |
| merge commit (`--no-ff`) | **WORKS**            | n/a — this is the target state |
| squash merge             | REFUSES              | yes                            |
| **rebase merge**         | **REFUSES**          | **yes**                        |
| cherry-pick integration  | REFUSES              | mostly — a deliberate act      |
| history rewrite          | REFUSES              | no — exceptional but real      |
| truly abandoned branch   | REFUSES              | no — discarding IS the intent  |

**Only the merge commit preserves ancestry.** That finding widened this plan's
scope: GitHub's "Rebase and merge" replays commits with new shas, so the branch
tip stops being an ancestor even though every commit survives individually. It
is the sneakier of the two, because nothing visibly disappears.

The prize is bounded and worth stating: with both banned, the force delete is
needed only for **truly abandoned work** and **history rewrites** — rather than
for every merged branch, forever.

Two corrections recorded because both were asserted before being checked:

1. "Squash merges mean we have to use the force delete" is **false** — the
   force flag is not required, because Plan 00206's `content-preserved` tier
   proves such a branch safe. The accurate claim is "squash merges mean `-d`
   can never be used": smaller, but still sufficient.
2. "Banning squash restores `-d`" is **incomplete** — it restores it only if
   the rebase merge is banned too.

## Tasks

### Phase 1: Handler (TDD)

- [ ] ⬜ **Task 1.1**: `pre_tool_use/ancestry_preserving_merge.py`
  - [ ] ⬜ Failing tests for `git merge --squash` and `gh pr merge --squash`
  - [ ] ⬜ Failing tests for `gh pr merge --rebase` — the case that widened
    this plan's scope, and the one most likely to be overlooked
  - [ ] ⬜ Failing tests for the evasion spellings Plan 00202 established:
    `git -C /path merge --squash`, a trailing-backslash continuation
  - [ ] ⬜ False-positive tests that must stay ALLOWED: `git merge` and
    `git merge --no-ff`, `gh pr merge --merge`, a LOCAL `git rebase main`
    (which preserves ancestry and is explicitly fine), and the words "squash"
    or "rebase" appearing in a commit message or filename
  - [ ] ⬜ Implement using the shared `utils/command_evasion.py` grammar rather
    than a bespoke regex
- [ ] ⬜ **Task 1.2**: `mode` option (`block` default, `warn`), mirroring
  `git_stash`, plus a `MUST_SQUASH_BECAUSE` escape hatch
- [ ] ⬜ **Task 1.3**: `get_claude_md()` explaining the ancestry consequence and
  naming the alternatives (`--no-ff` merge, rebase-then-fast-forward)

### Phase 2: Integrate

- [ ] ⬜ **Task 2.1**: Register in config; assign a priority in the 10–20 safety
  band alongside `destructive_git`
- [ ] ⬜ **Task 2.2**: `get_acceptance_tests()` covering block and allow cases
- [ ] ⬜ **Task 2.3**: `docs/guides/HANDLER_REFERENCE.md` entry; changelog and a
  `config-changes` manifest entry marking it `recommended: true`

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Full QA
- [ ] ⬜ **Task 3.2**: Daemon restart, verify RUNNING, probe every spelling
  against the live socket
- [ ] ⬜ **Task 3.3**: Confirm a `--no-ff` merged branch still deletes with plain
  `git branch -d`, which is the whole point of the plan

## Dependencies

- Depends on: Plan 00206 (delivered) — its `content-preserved` tier is what
  makes squash-merged branches deletable at all today
- Related: Plan 00202 (invocation-respelling hardening) — reuse its grammar so
  this handler is not bypassable on day one

## Technical Decisions

### Decision 1: Block by default, but keep it configurable

**Context**: Squash-only merging is enforced by policy in many organisations,
and GitHub repositories can be configured to permit no other merge method.

**Options Considered**:

1. Hard ban, no configuration — maximally consistent with the goal, but it
   would make the daemon unusable for teams whose platform mandates squash.
2. Opt-in, default off — safe, but a dormant guard protects nobody, which is
   the criticism v3.52.0 levelled at `sensitive_content` shipping inert.
3. Block by default with `mode: warn` and an escape hatch, exactly as
   `git_stash` already does for a comparable workflow opinion.

**Decision**: Option 3. It matches an established precedent in this codebase,
protects by default, and yields gracefully where the workflow is mandated
rather than chosen.

**Date**: 2026-08-12

## Success Criteria

- [ ] `git merge --squash`, `gh pr merge --squash` and `gh pr merge --rebase`
  are all DENIED by default
- [ ] Every Plan 00202 evasion spelling of those commands is also denied
- [ ] `git merge`, `git merge --no-ff`, `gh pr merge --merge` and a local
  `git rebase main` stay ALLOWED
- [ ] `mode: warn` downgrades to advisory; the escape hatch permits one
- [ ] The deny message explains the ancestry consequence, not a style opinion
- [ ] After a `--no-ff` merge, `git branch -d` deletes the branch — measured,
  not assumed, since that outcome is the entire point of the plan
- [ ] Full QA passes; daemon restarts RUNNING

## Risks & Mitigations

| Risk                                                          | Impact | Probability | Mitigation                                                                                            |
| ------------------------------------------------------------- | ------ | ----------- | ----------------------------------------------------------------------------------------------------- |
| Blocks a team whose platform mandates squash-only merging     | High   | Medium      | `mode: warn`, an escape hatch, and `enabled: false`; the decision records why a hard ban was rejected |
| The handler implies coverage of web-UI squash merges it lacks | Medium | Medium      | Non-Goals states it explicitly, and `get_claude_md()` must say so — the v3.52.0 over-claim lesson     |
| Bypassable by a respelling on day one                         | Medium | Low         | Built on the shared `command_evasion` grammar, with the evasion spellings tested up front             |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00207-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not started. Deferred out of v3.52.0 to avoid restarting that release's gates
  a third time; the release was already blocked for two days.
