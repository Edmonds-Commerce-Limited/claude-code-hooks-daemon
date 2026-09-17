# Plan 00433: setup worktree refuses to nest

**Status**: Complete
**Created**: 2026-09-17
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Thread

## Overview

A sub-agent dispatched with `isolation: "worktree"` already has its own isolated
checkout. A brief that ALSO tells it to run `./scripts/setup_worktree.sh` makes
it create a second worktree inside the first. That has happened, and it produced
95 bytes of directory before the socket filename was even appended — which is
where Plan 00431's 130-byte path came from.

The two conditions are independently reasonable and mutually invisible. The
agent cannot tell that its cwd is an isolation worktree rather than a normal
checkout, and the script does not know it is being run inside one. A worktree
carries the whole tree, `scripts/` included, so running the copy that is right
there is the natural thing to do — and `PROJECT_ROOT` is derived from the
script's own location, so the new worktree lands under the INNER checkout.

The path length is the visible half and Plan 00431 now catches it. The
expensive half is not about length: in the same run the agent's committed work
landed on a branch inside a tree the coordinator later reaped, a recovery
attempt began re-porting that work into the outer root, and the nested tree's QA
was graded against a daemon that had silently relocated to `/tmp` (Plan 00422
N9).

## Goals

- Running `setup_worktree.sh` from inside a linked worktree refuses, names the
  enclosing checkout, and prints the command to run instead.
- The documented child-worktree workflow — `worktree-child-<parent>-<task>`
  with a parent base branch — keeps working, because it is run from the main
  checkout.
- Nothing is created before the refusal.

## Non-Goals

- Changing how `isolation: "worktree"` dispatch works, or the guidance for
  writing briefs. That is the ledger's remedy (2), it is documentation only,
  and it relies on the next brief's author reading it — which is the failure
  mode here.
- Teaching the script to create the worktree in the OUTER checkout on the
  author's behalf. Guessing where someone meant to put a worktree is a larger
  decision than refusing with the command in hand.

## Tasks

### Phase 1: RED

- [x] ✅ **Task 1.1**: A test that runs the guard inside a real linked worktree
  and expects a refusal, plus the control that a normal checkout is allowed
  through. Four tests added to
  `tests/integration/test_worktree_socket_path_preflight.py`, alongside the
  socket guard they share a script with.

### Phase 2: GREEN

- [x] ✅ **Task 2.1**: Detect the nesting with
  `git rev-parse --git-dir` vs `--git-common-dir`, refuse, and name the
  enclosing checkout and the exact command to run there.

  Both paths are normalised to absolute. `--git-common-dir` answers relatively
  from a main checkout (`.git`) and absolutely from a worktree, so comparing
  them unnormalised would fire everywhere.

### Phase 3: Close

- [x] ✅ **Task 3.1**: Release note.
- [x] ✅ **Task 3.2**: Mark N9 remedied in the Plan 00422 ledger.

## Success Criteria

- [x] The refusal fires inside a linked worktree and does not fire in a normal
  checkout.
- [x] The message names the enclosing checkout, not just the fact of nesting.
- [x] Shellcheck and the deployed-asset lint gate stay green. 66 scripts, 0
  issues.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/11-setup-worktree-refuses-to-nest.md`

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00433-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from Plan 00422 niggle N9.
- Delivered at `ba7192b9` + the archiving commit.
- Verified live as well as in test, because the first live probe was
  MISLEADING: a worktree created with `git worktree add HEAD` carries the
  COMMITTED script, so it exercised the old one and refused for the socket
  length instead. Re-probed after committing — the nesting refusal fires and
  names `/workspace` — and the control was run live too: the main checkout still
  creates a worktree, venv and all, exit 0.
