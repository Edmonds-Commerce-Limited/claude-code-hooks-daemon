# Plan 00519: minimum tool versions and relative worktrees

**Status**: Blocked
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #110

## Overview

Issue #110 (ledger row N342) has two problems. `scripts/setup_worktree.sh`
cannot create a worktree from a host checkout whose path leaves no room for
the daemon's socket path. Git also records a worktree's link as an absolute
path, so a checkout used both on the desktop and in a container (where it is
at `/workspace`) has links that are wrong on one side.

The owner ruled on 2026-10-11 ([OWNER-RULINGS-261011.md](../00474-niggles-ledger-seventeen/OWNER-RULINGS-261011.md),
N342): require a git version that supports relative worktrees, declare
minimum versions for the tools the daemon needs (warn or error), and keep
worktrees as subdirectories of the repository by default.

**Blocked at triage on one fact.** Relative worktrees arrived in git 2.48.0
(`worktree.useRelativePaths`, `git worktree add --relative-paths`), and git
older than 2.48 refuses a repository once any worktree uses them. This
repository's own container runs **git 2.39.5** (measured 2026-10-14). Enforcing
2.48 today would make the daemon refuse its own development container, and
upgrading that git means changing the container image, which is outside the
agent's reach. Distribution-packaged git on long-term-support systems can
also be older than 2.48.

## Owner questions

1. **The container's git.** Should the container image move to git 2.48 or
   later first? Phase 2 cannot ship until it does.
2. **Clients on older git.** Turning relative worktrees on for a repository
   locks out every git older than 2.48 that touches it, a desktop client
   included. Should the daemon only enable it when every git that will open
   the repository is new enough (declared per project), or always?
3. **Severity per tool.** The ruling says warn or error. Proposed: git below
   the minimum is an error once relative worktrees are on, and a warning
   before then; python, uv and gh are warnings.

## Goals

- One declared table of the tools the daemon needs and the minimum version of
  each, checked at install, upgrade and session start.
- New worktrees use relative links, so they stay valid however the checkout
  is mounted.
- The socket-path limit has its own fix (issue #110, point 3).

## Non-Goals

- Upgrading anyone's git for them. The check reports; the human upgrades.
- Moving worktrees out of the repository.

## Tasks

### Phase 1: Declare and check minimum versions (not blocked)

- [ ] ⬜ **Task 1.1**: Inventory the external tools the daemon runs (git,
  python, uv, gh, and any others) and the oldest version each code path
  needs, with evidence per row.
- [ ] ⬜ **Task 1.2**: One table of minimum versions, read by install,
  upgrade and a SessionStart check, reporting each tool below its minimum at
  the severity the owner rules (question 3).

### Phase 2: Relative worktrees (blocked on questions 1 and 2)

- [ ] ⬜ **Task 2.1**: `setup_worktree.sh` and the worktree_create handler add
  worktrees with `--relative-paths` when git supports it and the project
  allows it.
- [ ] ⬜ **Task 2.2**: Convert existing absolute worktree links
  (`git worktree repair --relative-paths`), only where Task 2.1 applies.

### Phase 3: Socket-path limit

- [ ] ⬜ **Task 3.1**: Choose and build the fix for the socket-path limit
  (a shorter socket name, or acceptance gates following the socket discovery
  file). Relative worktree links do not shorten the socket path.

## Success Criteria

- [ ] Each tool below its declared minimum is reported at install, upgrade
  and session start, at its ruled severity.
- [ ] A worktree made in the container opens correctly from the desktop
  checkout, and the reverse.
- [ ] A worktree can be made from a host checkout at a long path.
- [ ] Release-bound consequences (a new minimum git, the new check) are in
  `CLAUDE/UPGRADES/UNRELEASED/` as a release note and, where config changes,
  a config-changes entry.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00519-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by the issue-sdlc loop from #110; blocked at triage on the container's
  git 2.39.5.
