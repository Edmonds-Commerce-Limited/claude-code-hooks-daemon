# Plan 00571: branch pools parked merged caps

**Status**: Complete
**Created**: 2026-11-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #165

## Overview

The WIP cap (`branches.wip.cap`, Plan 00558) counts every non-default branch as
one pool. Its deny message says "Finish, park or delete one", yet a parked
branch still counts (`docs/guides/CONFIGURATION.md` says so deliberately), so
parking never lowers the count (#165). Merged-but-undeleted branches count too.
On this repository's own sweep, five 58-day-old merged branches made up most
of a 9-of-10 count.

The owner ruled, in session, that branches split into three pools, each finite
and each ageing:

- **open work**: unmerged, unparked. The existing `wip.cap`.
- **parked**: shelved on purpose. A required reason (already true of
  `branch-park`), its own cap, and a max age after which the park is STALE and
  must be dealt with: finish, delete, or re-park with a fresh reason.
- **merged**: merged but not deleted. Its own cap. Keeping one needs a
  recorded reason, and a max age after which it is STALE and must go. An
  unkept merged branch is cleanup debt. The tooling has to make clearing it
  one deterministic, safe command.

Dogfooding the removal tooling the same day found gaps that this plan closes,
because a bulk removal is only safe when its recovery holds:

- `delete-branch` overwrites one fixed recovery bundle on every call, so only
  the last deleted branch can be restored (`daemon/cli.py` default `--bundle`,
  `daemon/branch_safety.py` `write_recovery_bundle`).
- The sweep's "merged, not deleted" list prints one `delete-branch` per branch
  and never names `branch-sweep --clean`, which is the bulk tool that already
  exists.
- `branch-sweep --clean` deletes local branches only. Merged REMOTE branches
  get per-branch `git push --delete` advice.
- `worktree-reap --reap-branches` skips non-agent-named merged branches
  silently. The skip is intended (Plans 00048/00349), but never reported.

Root-cause detail with file:line: [ROOTCAUSE.md](ROOTCAUSE.md).

## Goals

- Three pools with separate caps, each deny offering only actions that lower
  THAT pool's count.
- Parked and merged branches carry a recorded reason and age into a STALE state
  past their max age, surfaced by the sweep, SessionStart and the creation
  guard in the same staged way dormancy is.
- One deterministic command clears every provably merged, unkept branch, local
  and remote, behind a recovery bundle that accumulates rather than overwrites.
- Every report that lists a merged branch names that one command.

## Non-Goals

- Changing dormancy for open work, or the containment proof (Plan 00570, #166).
- Deleting anything without proof, or deleting a kept branch inside its age.
- `work-queue done` naming the issue it just delivered as the next workable one
  ([ROOTCAUSE.md](ROOTCAUSE.md) item 3). Recorded as N582 in the open niggles
  ledger (Plan 00474).

## Design decisions to settle in Phase 1 (with evidence, before code)

- **Where a merged branch's keep-reason lives.** A commit (as `branch-park`
  does) would make the branch unmerged, so that route is out. Candidates are a
  git note under a daemon ref (pushable, travels with clones) or a tracked
  file. Pick one, state why, and make it readable by the sweep without
  network.
- **Defaults** for `parked.cap`, `parked.max_age_days`, `merged.cap` and
  `merged.max_age_days`, and the mode keys (`block`/`warn`/`off`) mirroring
  `wip.mode`. Each value is justified, with no magic numbers.
- **What re-parking a stale park does**: it resets the age only with a new
  reason, and the count of re-parks stays visible in the trailer history.
- **Config migration**: the new keys are additive with defaults. Record a
  `config-changes` entry and a `truth-changes` entry, because the documented
  truth "parked still counts against the WIP cap" becomes false.

## Tasks

### Phase 1: Design

- [x] ✅ **Task 1.1**: Settle the decisions above in `DESIGN.md`, citing
  Plan 00558's design.

### Phase 2: Safe removal tooling first (needed by everything else)

- [x] ✅ **Task 2.1**: The recovery bundle accumulates: one bundle per call,
  timestamped with a random suffix, as `branch-sweep --clean` already does,
  and a restore line per branch with full refspecs. Test five sequential
  deletes, then restore all five.

- [x] ✅ **Task 2.2**: `branch-sweep --clean` also removes provably merged
  REMOTE branches (opt-in flag, or the default under a config key), and
  respects keep-records.

- [x] ✅ **Task 2.3**: The sweep, the cap deny and the stop guard name
  `branch-sweep --clean` whenever a merged branch is listed.

- [x] ✅ **Task 2.4**: `worktree-reap --reap-branches` reports each merged
  branch it skipped because of its name, and points at `branch-sweep --clean`.

- [x] ✅ **Task 2.5**: The branch stop guard treats a branch named by a
  `running` work-queue record as handed over, not abandoned. This is niggle
  N581, reproduced while this plan's own sub-agent was committing to
  `worktree-plan-00571-branch-pools`: the coordinator's stop was told to push
  or finish that branch, with "abandoned" threatened at the third block.

- [x] ✅ **Task 2.6**: `CLAUDE/development/IssueSdlc.md` Step 5 stops
  requiring a separate integration branch when only one branch is ready. It
  merges current `main` into the issue branch itself and runs the targeted
  check there. Found dogfooding: every issue opened two branches, and the
  creation guard's own hint ("continue there instead of opening another")
  fired on the runbook's second one.

- [x] ✅ **Task 2.7**: Reconcile the remote-proof helpers. Plan 00570 added
  `utils/remote_refs.py` (one lazy `ls-remote` for `branch-sweep` and
  `delete-branch`). This plan's remote `--clean` must reuse it, not add a
  second module. Also make `core/branch_stop_gate.py`'s
  `_running_queue_branches` delegate to `core/agent_ownership.running_holds`
  rather than keep its own copy of the queue read.

- [x] ✅ **Task 2.8**: `branch-sweep --clean [--remote]` and `worktree-reap`
  leave a live agent's worktree and branch alone: a `running` work-queue
  record, a worktree under the harness's `.claude/worktrees/` (`--clean`
  only), or a git lock. Found dogfooding: a dry run would have removed a sub-agent's
  fresh isolation worktree, whose branch sat at main's tip and so read as
  merged. Logic in `core/agent_ownership.py`.

### Phase 3: Pools

- [x] ✅ **Task 3.1**: Failing tests: parked branches leave the wip count;
  the parked cap denies with park-specific actions; a stale park is surfaced
  and staged; merged branches leave the wip count; the merged cap denies
  naming `branch-sweep --clean`; a kept merged branch is exempt inside its age
  and stale past it.
- [x] ✅ **Task 3.2**: Implement the config keys and pool counting in
  `core/branch_creation.py` and `core/branch_inventory.py`, plus the
  `branch-keep` (or equivalent) command for merged branches.
- [x] ✅ **Task 3.3**: Update docs (`docs/guides/CONFIGURATION.md` branches
  section, handler guidance) and add the release note, config-changes and
  truth-changes entries. Done in five slices (a–e); report
  [phase-3-pools-impl-be.md](subagent-reports/phase-3-pools-impl-be.md).

### Phase 4: Dogfood

- [x] ✅ **Task 4.1**: Run the sweep, `--clean` and the pools on this
  repository and journal what each produced. Open work went from 10 of 10
  (cap-blocked) to 1 of 10; three merged agent branches were reaped and
  cleaned, remote included, behind one recovery bundle. The skip line for a
  Claude-owned worktree now names `worktree-reap --reap --only <name>`.

## Success Criteria

- [x] Each pool's deny offers only actions that lower its own count (#165's
  defect is gone): `tests/unit/core/test_branch_pools.py` (each pool denies
  under its own rule; the WIP deny lists open work only).
- [x] Five sequential `delete-branch` calls leave all five restorable:
  `test_cli_delete_branch_bundles.py::test_five_sequential_deletes_are_all_restorable`.
- [x] One command clears every provably merged, unkept branch, local and
  remote: `branch-sweep --clean --remote`. A branch whose worktree is under
  `.claude/worktrees/` (Claude Code's) is skipped by design and its skip
  line names `worktree-reap --reap --only <name>`, which removes it first.
- [x] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
  (`007-branch-pools-parked-merged-caps.md`), plus config-changes and
  truth-changes entries, sit in the pending-release holding area.
- [x] Issue #165 is commented and closed after a verified merge and green CI
  (`main` run 42430377951 green at 7a917cff9).

## Delivery & Milestones

- Phases 1 and 2 merged to `main` earlier (Task 2.7 and its siblings).
- Phase 3 merged at 9314a6e4c through PR #186, whose CI ran the full gate.
- Phase 4 dogfood journalled on 2026-11-08 (fix 7a917cff9); `main` CI green
  at 7a917cff9; #165 commented and closed.
