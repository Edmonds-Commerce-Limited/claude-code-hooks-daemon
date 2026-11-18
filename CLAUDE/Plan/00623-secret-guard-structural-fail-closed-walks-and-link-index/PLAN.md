# Plan 00623: secret guard structural fail closed walks and link index

**Status**: Not Started
**Created**: 2026-11-18
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The secret and flaggable guards keep producing the same defect class: a bounded walk (link scan, directory walk, placement, nesting depth) that stops early and ALLOWS. Six review rounds on Plan 00614 found it again each time, in a different walk. Fixing each instance leaves the next one in place, because every walk reports "I stopped" in its own way, or not at all.

The branch `agent-a13d7c8504105d4c9-aeae03b4` (Plan 00614, tip 2ae46b106, fix round 6, not merged) fixes the known instances and has 0 DENY-to-ALLOW over 2,451 corpus commands. It is held because it over-denies. In a project past 512 directories, a computed `cd` followed by a relative word is denied as "could not be worked out". The Usability finding in `CLAUDE/Plan/00614-secret-guard-resolves-links-against-hook-cwd/subagent-reports/261118-independent-review-2.md` lists 5 examples (a `cd "$D"` then a recursive grep, `cd -`, a home-relative move, a move to `$TMPDIR` or `mktemp -d`, and a loop or `dirname "$0"` move). Most real repositories exceed 512 directories, so the over-deny would be the common case.

This plan removes the cause rather than raising the cap: one shared result type that says whether a walk finished, one shared fail-closed handler for both guards, and a link index built once and invalidated, so no command walks the tree and the cap stops mattering. Moves that land outside the project (`~`, `$HOME`, `$TMPDIR`) are placed so they are not denied. Plan 00614's branch is then merged. Also covered: ledger items N663 (a relative word that fits `PATH_MAX` only relative to the hook cwd) and N664 (a recursive search nested 5 or more `bash -c` levels deep).

## Goals

- One shared "did it finish" result type for every bounded walk (link scan, directory walk, placement, nesting depth), so an unfinished walk cannot be read as "nothing found".
- One shared fail-closed handler used by both the secret guard and the flaggable guard.
- An off-hot-path link index, built once and invalidated, not walked per command, so the 512 directory cap stops mattering.
- Place `~`, `$HOME` and `$TMPDIR` so moves that land outside the project are not denied.
- Merge Plan 00614's branch with these in place.

## Non-Goals

- Any loosening of what is denied today. A command denied on main stays denied.
- New secret-path classes or new reader verbs.

## Tasks

### Phase 1: Shared result type and handler

- [ ] ⬜ **Task 1.1**: Write failing tests for each walk that stops early today (link scan, directory walk, placement including N663, nesting depth including N664), asserting a deny.
- [ ] ⬜ **Task 1.2**: Introduce the shared "finished or not" result type and convert every bounded walk to return it.
- [ ] ⬜ **Task 1.3**: Introduce the shared fail-closed handler and route both guards through it.

### Phase 2: Link index

- [ ] ⬜ **Task 2.1**: Build the link index once per project, invalidated on change, and read it instead of walking per command.
- [ ] ⬜ **Task 2.2**: Place `~`, `$HOME` and `$TMPDIR` so a move that lands outside the project is not denied.
- [ ] ⬜ **Task 2.3**: Add the review report's 5 usability examples as tests in a project past 512 directories where no link reaches a protected path.

### Phase 3: Merge and review

- [ ] ⬜ **Task 3.1**: Rebase or merge the Plan 00614 branch onto this work and resolve conflicts.
- [ ] ⬜ **Task 3.2**: Run the DENY-to-ALLOW comparison against main and an independent adversarial review.

## Success Criteria

- [ ] 0 DENY-to-ALLOW against main over the existing corpus plus the Plan 00614 probes.
- [ ] The usability examples in the second review report are allowed again in a project past 512 directories where no link reaches a protected path.
- [ ] An independent adversarial review passes.
- [ ] A pending-release holding-area release note is written.
- [ ] N663 and N664 are closed in the niggles ledger.

## Delivery & Milestones

- Not started.
