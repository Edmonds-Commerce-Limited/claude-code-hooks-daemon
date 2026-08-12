# Plan 00206: safe branch delete deterministic proof

**Status**: Complete
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`destructive_git` blocks the force branch delete unconditionally, and the safe
lowercase form refuses any branch git considers unmerged. Between those two
sits a large class of branches that legitimately need deleting and cannot be:
stale agent branches, abandoned spikes, and — as of the v3.52.0 history rewrite
— every branch whose commits are no longer ancestors of the rewritten `main`.
The only route today is to ask a human, which is exactly what happened during
the v3.52.0 release and stalled it for an extended period.

The gap is not that the guard is wrong. It is that the project offers **no
deterministic path to a provably safe deletion** — so the guard's only outcome
is escalation, on every branch, forever. This plan adds that path: a
`hooks-daemon delete-branch` command that refuses by default and deletes only
what it can positively prove is recoverable, printing the evidence either way.

Design is evidence-led. Probing the seven real stale branches in this repo
showed that neither of the two obvious proofs is sufficient on its own: none is
an ancestor of `main` (so the lowercase form refuses all seven), yet 925–1408
commits per branch **are** patch-equivalent upstream because the rewrite
preserved patch-ids while changing shas. A residual 57–65 commits per branch are
unique by patch-id. A single-check design would therefore either refuse
everything or approve on a proof that does not hold.

## Goals

- Add `hooks-daemon delete-branch` with a **tiered, fail-fast proof model**:
  refuse unless a branch reaches a sufficient tier, and always print which tier
  it reached and why.
- Make deletion **reversible by default** — write a recovery bundle before
  deleting, with an explicit opt-out for the case where the branch content is
  precisely what must be destroyed.
- Make the residual risk **visible rather than assumed**: when a branch cannot
  be proven lossless, report exactly what is unique to it (counts and paths,
  never file contents) so the decision is informed.
- Give `destructive_git` a remedy to name, so its block message stops being a
  dead end and points at the sanctioned path.

## Non-Goals

- No weakening of `destructive_git`. The force-delete stays blocked; this adds a
  checked alternative rather than an exemption, and the new command performs
  strictly **more** verification than the flag it replaces.
- No remote branch deletion. Local refs only — deleting a published branch is a
  different risk class and needs its own decision.
- No automatic reaping of stale branches. This plan builds the safe mechanism;
  deciding *which* branches are stale stays with the caller.

## Context & Background

Measured on this repository's seven stale branches:

| Proof                                      | Result                                |
| ------------------------------------------ | ------------------------------------- |
| tip is ancestor of `main`                  | false for all seven                   |
| commits patch-equivalent upstream          | 925–1408 per branch                   |
| commits unique by patch-id                 | 57–65 per branch                      |
| files present on branch but absent on main | 12–39 per branch, all deleted-by-main |

The last row is the one that matters and the one no built-in git check
performs: every "branch-only" file turned out to be a file `main` itself
created, evolved and later deleted — each had 3–9 commits in `main`'s own
history. Commit-level uniqueness does not imply content loss, which is why the
tool must reason about content, not just commits.

## Tasks

### Phase 1: Proof engine (TDD)

- [x] ✅ **Task 1.1**: `daemon/branch_safety.py` with pure, testable functions
  - [x] ✅ `classify_branch()` returning a tier + evidence dataclass
  - [x] ✅ Tier MERGED: tip is an ancestor of a protected ref
  - [x] ✅ Tier PATCH_EQUIVALENT: zero `+` lines from `git cherry`
  - [x] ✅ Tier CONTENT_PRESERVED: every blob in the branch tip is reachable
    from the protected ref. Replaced the drafted path-level `CONTENT_SUBSUMED`
    tier, which could have approved a lossy deletion — see the 07:52 journal
    entry
  - [x] ✅ Tier UNPROVEN: anything else, enumerating the CONTENT-unique files
- [x] ✅ **Task 1.2**: Blocking preconditions, each independently tested
  - [x] ✅ refuse the current branch
  - [x] ✅ refuse a branch checked out in any worktree
  - [x] ✅ refuse a protected branch name (configurable list)
  - [x] ✅ refuse a name that does not resolve to a local branch

### Phase 2: Command surface

- [x] ✅ **Task 2.1**: `cmd_delete_branch` wired into the CLI
  - [x] ✅ all-or-nothing: classify every branch first, delete only if all pass
  - [x] ✅ `--dry-run` prints the classification and deletes nothing
  - [x] ✅ `--format json` for machine consumption
- [x] ✅ **Task 2.2**: Recovery bundle written before deletion by default,
  with `--no-bundle` for the deliberate-destruction case
- [x] ✅ **Task 2.3**: `--allow-unproven` gate, refused unless a reason string
  is supplied, so an unproven deletion is always recorded with its rationale
- [x] ✅ **Task 2.4**: Abandonment is human-gated — the engine requires a
  `confirm` callback before deleting any `unproven` branch, and the CLI supplies
  one only when `stdin` is a real terminal
  - [x] ✅ the flags declare intent; the terminal prompt asks for consent, which
    the party requesting the deletion cannot grant itself
  - [x] ✅ no TTY ⇒ `confirm=None` ⇒ refused as "no confirmation channel", never
    misreported as "a human declined"
  - [x] ✅ consent is the word `abandon`, not `y` — one keystroke is too easy to
    fat-finger for discarding the only copy of work
  - [x] ✅ the prompt lists only the `unproven` branches; listing safe ones would
    train a human to skim

### Phase 3: Close the loop

- [x] ✅ **Task 3.1**: `destructive_git.get_claude_md()` names the new command
  as the sanctioned remedy, so the block message is no longer a dead end
- [x] ✅ **Task 3.2**: `docs/guides/HANDLER_REFERENCE.md` updated to match
- [x] ✅ **Task 3.3**: Dogfood — all seven stale branches classified `unproven`,
  reviewed, and deleted with `--allow-unproven --reason ... --no-bundle`

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Full QA — 20/20, 11,499 passed / 0 failed / 5 skipped,
  coverage 95.2%
- [x] ✅ **Task 4.2**: Daemon restart, verify RUNNING (no import errors in logs)
- [x] ✅ **Task 4.3**: Client-mode verification via `scripts/dummy-client-repo.sh`
  — the gate refuses an abandonment with every flag declared and no TTY (exit 1,
  branch intact), while a `--no-ff` merged branch still deletes unprompted with
  no flags (exit 0). Run against the PRE-gate install first, which deleted the
  branch (exit 0), so the fixture is demonstrated to be capable of showing the
  failure it now shows fixed

## Dependencies

- Related: Plan 00205 (synonym respellings) — that plan closes plumbing routes
  *around* the guard; this one opens a checked route *through* it. Both are
  needed: without this, closing the plumbing routes leaves no exit at all.

## Technical Decisions

### Decision 1: A checked command, not an escape hatch

**Context**: The obvious cheap fix is an escape-hatch environment variable, in
the style of `MUST_STASH_BECAUSE`.

**Options Considered**:

1. Escape-hatch variable on `destructive_git` — trivial, but it verifies
   nothing. It converts a hard block into a soft one and trusts the caller's
   assertion, which is the failure mode the daemon exists to prevent.
2. A separate command that performs real checks — more work, but the deletion
   becomes *earned* rather than *asserted*.

**Decision**: Option 2. An escape hatch would have let the v3.52.0 release
proceed while proving nothing about the seven branches; the checks are the
entire value. A guard whose only bypass is a declaration of intent teaches
agents that declaring intent is how you get past guards.

**Date**: 2026-08-12

### Decision 2: Reversible by default, destructive on request

**Context**: The motivating case is branches whose unique content is exactly
what a history rewrite was run to destroy. A recovery bundle would preserve it.

**Decision**: Write the bundle by default so ordinary use is undoable, and
require `--no-bundle` to opt out. The safe behaviour is the default; the
irreversible one is typed deliberately.

**Date**: 2026-08-12

### Decision 3: Intent is not consent — abandonment needs a human

**Context**: `--allow-unproven --reason "..."` originally sufficed to delete a
branch holding the only copy of real work. But every other tier is a *proof*,
and a proof can be acted on unattended precisely because it is checkable.
`unproven` is the case where evidence ran out and judgement takes over.

**Options Considered**:

1. Flags alone — self-consistent, but it makes the guard's only bypass "declare
   loudly that you meant it", which is exactly the lesson Decision 1 refused to
   teach.
2. Refuse `unproven` outright — safest, but wrong: a genuinely abandoned branch
   must be deletable, and a tool with no route for it is a tool people work
   around.
3. Require a human at an interactive terminal, in addition to the flags.

**Decision**: Option 3. The flags declare *intent*; the prompt asks for
*consent*, and the party that wants a deletion cannot grant its own permission
for it. An agent's shell has no TTY, so this is structural rather than
policy-based — there is nothing to remember or comply with. The three provable
tiers are untouched and never prompt, so automation loses nothing it could
justify.

**Date**: 2026-08-12

## Success Criteria

- [ ] A merged branch deletes with no flags
- [ ] A branch whose commits are patch-equivalent upstream deletes with no flags
- [ ] A branch with genuinely unique content is REFUSED by default, and the
  refusal names the unique paths
- [ ] The current branch and any worktree-checked-out branch are always refused
- [ ] A recovery bundle exists after a default-mode deletion, and restores the
  branch
- [ ] `destructive_git`'s block message names the new command
- [ ] An `unproven` deletion is refused with every flag declared when there is
  no terminal, and the safe tiers still delete unprompted — measured through the
  real CLI, not only unit tests
- [ ] Full QA passes; daemon restarts RUNNING

## Risks & Mitigations

| Risk                                                              | Impact | Probability | Mitigation                                                                                   |
| ----------------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------------------- |
| The tool becomes a rubber stamp agents pass `--allow-unproven` to | High   | Medium      | Unproven mode demands a reason string and prints the full unique-path evidence before acting |
| A proof tier is subtly wrong and approves a lossy deletion        | High   | Low         | Bundle-by-default makes any wrong approval recoverable; each tier is independently tested    |
| Content comparison is slow on large repositories                  | Low    | Medium      | Tiers are evaluated cheapest-first and short-circuit on the first that holds                 |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00206-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan created; proof model derived from measurements on seven real branches.
- Proof engine, CLI, guidance and dogfooding delivered in `45da2af1` (the
  v3.52.0 release commit); the seven stale branches were classified, reviewed
  and removed, taking `git_history` from 29 violations to 0.
- Abandonment made human-gated, and three release-time upgrade gates fixed, in
  `69475dbc`. Verified in a real client install both ways: refused with every
  flag and no TTY, still automatic for a provably merged branch.
