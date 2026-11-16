# Plan 00613: worktree link secret verb

**Status**: Not Started
**Created**: 2026-11-16
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A peer project reports a guard gap: `R-SECRET-BASH-MENTION` denies any command
that names a protected path, which includes creating a relative symlink to a
protected file (a vault password file) from inside a registered git worktree.
The link reads no content, yet the peer's worktree workflow requires exactly that
link, so no agent can bootstrap a worktree and every lane routes through the
main checkout. The peer proposes a sanctioned verb (for example
`hooks-daemon worktree-link-secret <worktree> <name>`) that creates only a
relative symlink to a protected file of the primary checkout, only inside a
worktree registered to that repository, and never reads, copies or prints
content.

This plan is DESIGN FIRST. The secret guard exists so that a protected file's
contents never reach an agent by any route, and a link is a route: a worktree
path that resolves to the protected file lets every later `Read`, `cat` or copy
of that worktree path reach the content, past the guard's path matching unless
it resolves links. The statement that the owner has said agents may link their
own worktree files came from a peer and is not verified here.

## Goals

- Decide, with the owner, whether a worktree link to a protected file is
  acceptable at all, and under what conditions.
- If yes, a verb that creates only that link and nothing else, with the guard
  unchanged for every other mention.

## Non-Goals

- Loosening `R-SECRET-BASH-MENTION` for any command other than the verb.
- Copying or printing a protected file, or any absolute link.

## Tasks

### Phase 1: Design and owner decision

- [ ] ⬜ **Task 1.1**: Establish by running whether a symlink inside a worktree to
  a protected primary-checkout file is judged by the guard on its RESOLVED path
  when read through the link (`Read`, `cat`, `grep`, an interpreter one-liner).
  If it is not, the verb opens a hole and the guard must resolve links first.
- [ ] ⬜ **Task 1.2**: Write DESIGN.md: the threat model, the verb's argument
  checks, how the protected set is read (never its content), and the owner
  question: is a link acceptable, and is the instruction from the owner
  verified in a human line of the team history.
- [ ] ⬜ **Task 1.3**: Owner decision recorded in the plan journal before any code.

### Phase 2: Implementation (only after 1.3 says yes)

- [ ] ⬜ **Task 2.1**: Test-first: the verb refuses a non-worktree target, an
  absolute link, a copy, any path outside the primary checkout's protected set,
  and an existing destination; it creates exactly one relative symlink otherwise.
- [ ] ⬜ **Task 2.2**: The guard keeps denying every other mention; a test pins
  that a hand-typed `ln -s` of a protected path is still denied.
- [ ] ⬜ **Task 2.3**: Release note.

## Success Criteria

- [ ] The owner decision is on record before any code.
- [ ] If built: all the refusals above are tested and the guard is otherwise unchanged.
- [ ] Release-bound consequences recorded in the pending release notes, or the
  plan states there are none because nothing shipped.

## Delivery & Milestones

- Filed from a peer report; no delivery yet.
