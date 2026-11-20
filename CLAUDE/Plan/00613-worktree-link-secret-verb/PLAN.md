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
main checkout.

The owner decided (2026-11-20, quoted in
[DESIGN.md Owner decision](DESIGN.md#owner-decision)): linking a protected file
into a worktree is allowed and needed, in link mode only. The route is owned by
the project config (the `worktree_create` seed list) and run by the creation
hook or by `hooks-daemon seed-worktree <worktree>` for a hand-made worktree;
neither lets an agent name a path to link. A read through the link is judged
as a read of the file, including a recursive read that follows links below its
root (`utils/link_reach.py`, closing the gap the 261120 handoff recorded).

## Goals

- A protected file can be seeded into a worktree as a relative link, by the
  creation hook and, for a hand-made worktree, by `seed-worktree`.
- Copy mode stays refused for a protected source; each protected link is audited.
- Reads through a seeded link stay denied, including link-following recursive reads.

## Non-Goals

- Loosening `R-SECRET-BASH-MENTION` for any command at all.
- An agent-invocable verb that takes a path to link (DESIGN sections 3 to 8).
- Copying or printing a protected file, or any absolute link.

## Tasks

### Phase 1: Design and owner decision

- [x] ✅ **Task 1.1**: (Done: three gaps found, report in
  `subagent-reports/261116-symlink-resolution.md`, fixed under Plan 00614.)
  Establish whether a link to a protected file is judged on its resolved path.
- [x] ✅ **Task 1.2**: (Done: [DESIGN.md](DESIGN.md).) Threat model, verb
  checks, how the protected set is read, owner questions.
- [x] ✅ **Task 1.3**: (Done: delegated ruling 2026-11-19, then the owner's
  own answer 2026-11-20; see DESIGN and the journal.)

### Phase 2: Tighten the seeding executor

- [x] ✅ **Task 2.1**: (Done.) Refuse `mode: copy` for a protected seed source;
  an unreadable protected set refuses every copy.
- [x] ✅ **Task 2.2**: (Done.) One audit line per protected link, written before
  the link, in `worktree-seed-protected-links.jsonl`.
- [x] ✅ **Task 2.3**: (Done: a pin.) A hand-typed `ln -s`, `ln` or `cp` naming a
  protected path stays denied by `R-SECRET-BASH-MENTION`.
- [x] ✅ **Task 2.4**: (Done.) Release callout 009 and pre-upgrade task 01.
- [x] ✅ **Task 2.5**: (Done.) `check-worktree-seed` reports refused copies.

### Phase 3: Make the link route work

- [x] ✅ **Task 3.1**: (Done: a pin,
  `test_secret_file_guard_seeded_link_reads.py`.) DESIGN section 8 group C
  against links `seed_worktree` placed, hook cwd in the worktree: Read, Edit,
  Grep and relative Bash reads denied. Run through the handler, not a live
  daemon socket.
- [x] ✅ **Task 3.1b**: (Done.) Close the link-following read gap: a recursive
  reader that follows links (`grep -R`, `find -L`, `find -exec`, `zip`, ...) is
  judged on what lies behind each link below its root (`utils/link_reach.py`);
  the strict-xfail is now passing cases with controls.
- [x] ✅ **Task 3.2**: (Done.) Documentation: HANDLER_REFERENCE, the example
  config, the handler's CLAUDE.md guidance, callout 009 and task 01 now point
  a protected copy at symlink mode.
- [x] ✅ **Task 3.3**: (Done.) `hooks-daemon seed-worktree <worktree>` applies
  the configured list to a hand-made worktree; one positional, no options;
  release note 018. A protected link entry must also be listed in the config
  committed at HEAD (residual 1 of the 261120 handoff, narrowed).
- [ ] ⬜ **Task 3.4**: Reply to the peer project with the route (coordinator).

## Success Criteria

- [x] The decision is on record before any code (delegated ruling, then the
  owner's own answer, quoted in DESIGN).
- [x] The copy refusal, the audit line and `seed-worktree` are tested, the
  refusal and audit tests seen failing first. (Exceptions, journalled: the
  pins of Tasks 2.3 and 3.1, two handler wiring tests for 2.2, and the
  `seed-worktree` CLI wrapper test.)
- [x] The guard denies every mention it denied before.
- [ ] Every read through a seeded link is denied, verified through a live daemon
  socket. (Through the handler: all pinned cases denied, the link-following
  gap included; the live-socket check is still open.)
- [x] Release-bound consequences recorded in the pending release notes
  (`CLAUDE/UPGRADES/UNRELEASED/release-notes/009-*` and `018-*`) and the
  pre-upgrade tasks (`CLAUDE/UPGRADES/UNRELEASED/pre-upgrade-tasks/01-*`).

## Delivery & Milestones

- Phases 1 to 3 built on the work branch, not yet merged; an independent
  security review follows before merge.
