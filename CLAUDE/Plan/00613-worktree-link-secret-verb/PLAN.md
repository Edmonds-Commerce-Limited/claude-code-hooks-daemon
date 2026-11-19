# Plan 00613: worktree link secret verb

**Status**: In Progress
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

- [x] ✅ **Task 1.1**: (Done: three gaps found, report in
  `subagent-reports/261116-symlink-resolution.md`, fixed under Plan 00614.)
  Establish by running whether a symlink inside a worktree to
  a protected primary-checkout file is judged by the guard on its RESOLVED path
  when read through the link (`Read`, `cat`, `grep`, an interpreter one-liner).
  If it is not, the verb opens a hole and the guard must resolve links first.
- [x] ✅ **Task 1.2**: (Done: [DESIGN.md](DESIGN.md); recommends the shipped
  config seed list over a new verb, gated on Plan 00614.) Write DESIGN.md: the threat model, the verb's argument
  checks, how the protected set is read (never its content), and the owner
  question: is a link acceptable, and is the instruction from the owner
  verified in a human line of the team history.
- [x] ✅ **Task 1.3**: (Settled by a fable sub-agent under the owner's
  delegation, 2026-11-19, not the owner's own words; see
  [DESIGN.md Rulings](DESIGN.md#rulings) and the journal.) Decision recorded
  in the plan journal before any code: no agent-invocable verb; config
  seeding in link mode plus a human-run step; copy mode refused for a
  protected source. The verb is reopened only by the owner's own typed yes.

### Phase 2: Tighten the seeding executor (may start now; it only tightens)

- [ ] ⬜ **Task 2.1**: Test-first: `utils/worktree_seeding.py` refuses
  `mode: copy` for a seed source the secret guard protects, using the guard's
  own matcher over paths only (never content). The refusal names the check
  and the seed by role. A config that cannot be read refuses the protected
  decision rather than falling back. An unprotected seed and a protected seed
  in link mode behave as today.
- [ ] ⬜ **Task 2.2**: Test-first: each protected source seeded as a link
  appends one audit line (DESIGN section 7 fields; never content, size or
  digest) to a daemon-owned log under the primary checkout's daemon
  `untracked/` directory.
- [ ] ⬜ **Task 2.3**: A test pins that a hand-typed `ln -s`, `ln` or `cp`
  naming a protected path is still denied by `R-SECRET-BASH-MENTION`.
- [ ] ⬜ **Task 2.4**: Release note for 2.1 and 2.2 (a config that seeds a
  protected file in copy mode now refuses; say what to change).

### Phase 3: Advise the link (gated)

Gate: Plans 00614 and 00623 merged to `main`, and the three link routes
verified denied through a live daemon socket.

- [ ] ⬜ **Task 3.1**: DESIGN section 8 group C, end to end against a seeded
  link in a client-mode fixture, through a live daemon.
- [ ] ⬜ **Task 3.2**: Install-guide text: how a project declares a protected
  seed in link mode, and the human-run step for a hand-made worktree. Reply to
  the peer project with the route.

## Success Criteria

- [x] The decision is on record before any code (a delegated ruling, see Task 1.3).
- [ ] The copy refusal and the audit line are tested, each test seen failing
  first, and the guard denies every mention it denied before.
- [ ] No text advising a protected seed or hand link ships before the Phase 3 gate.
- [ ] Release-bound consequences recorded in the pending release notes.

## Delivery & Milestones

- Filed from a peer report; no delivery yet.
- Design questions Q0 to Q5 settled by delegated ruling; Phase 2 is ready to build.
