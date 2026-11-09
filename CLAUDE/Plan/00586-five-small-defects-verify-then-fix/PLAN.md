# Plan 00586: five small defects, verify then fix

**Status**: Not Started
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Seven small defects were noticed in passing during other work and recorded nowhere. Owner ruling: a finding gets a plan
(`CLAUDE/Worktree.md`, "Small Batches"). Three of them (A, B, D) came from review agents and have not been reproduced,
so every task starts by reproducing the defect. A task whose defect does not reproduce closes with the evidence that it
does not, and no change.

- **A.** `check-config-migrations` recommends handlers that have since been removed.
- **B.** `daemon.languages: []` is read as "no languages" rather than as unset.
- **C.** The `/hooks-daemon optimise` procedure (`optimise.md` and
  `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/optimise-invoke.sh`) gives wrong paths when the daemon is
  self-installed, as in this repository. Fact-check: the script itself already resolves the self-install daemon
  directory, so the wrong paths, if real, are in the procedure text it prints.
- **D.** In the release-gate workflow, a failing shard does not cancel the other shards, so a run that has already
  failed keeps using runners. Fact-check: `fail-fast: false` is set in `release-gate.yml` and in the shared
  `test-shards.yml`, and `qa.yml` says deliberately that one failing check must not hide the others. So the question
  is whether the release gate, unlike the per-push run, should stop at the first failure.
- **F.** The `git restore` guard (R-GIT-RESTORE) refuses to restore a tracked file whose working copy is EMPTY, as a
  host reboot left one in this repository. Discarding an empty working copy loses nothing, since there is no content
  to lose, but the guard denies it and only a human can run the restore.
- **G.** CI's change-to-test mapping does not select `tests/integration/test_client_owned_asset_lint.py` when a
  client-shipped shell asset changes. Seen: Plan 00581 changed `provision.sh` (`cfa601263`); its CI run (42650039659)
  skipped the full suite, the mapping did not pick the asset lint test, and the "Shell" job passed. The SC2030/SC2031
  regression reached main and was caught only by a later full-suite fallback run (42676054890); fixed in
  `43f1a9a98`.
- **E.** The plan-number guard (`plan_number_helper`, R-PLAN-NUMBER-DISCOVERY) blocks a command that combines an
  `ls ... | awk` with `git add CLAUDE/Plan/...`, which discovers no plan number.

Dedupe scout (all 70 live plans checked before this one was filed): no live plan covers B, C, D or E. A overlaps Plan 00420 (fail-fast
config migration of retired handler keys), which is a superset: if 00420 is in progress when A is reached, A moves
there. Prior art: Plan 00323 (a contract test against the optimise checklist naming retired handlers; relevant to A
and C), Plans 00227 and 00138 (earlier false-positive fixes of the same guard as E).

## Goals

- Each of A to G is either fixed with a test that failed before the fix, or closed with the evidence that it does not
  reproduce.

## Non-Goals

- Plan 00420's wider config-migration work.
- Plan 00421's choice of which checks run in CI (D is job cancellation only).

## Tasks

### Phase 1: Verify and fix (one task per defect, independent)

- [ ] ⬜ **Task 1.1 (A)**: Reproduce: list every handler `check-config-migrations` can recommend and compare it with
  the registered handlers. RED test, then fix the source of the recommendation. Check Plan 00420 first

- [ ] ⬜ **Task 1.2 (B)**: Reproduce with a config holding `daemon.languages: []`. Fact-check: plausibly real, the
  two readers disagree (`core/relevance.py` treats `[]` as an empty set, `core/apply_once.py` treats it as unset).
  Decide which reading the config documentation promises; RED test for that reading, then fix the loader (or the documentation, if the code matches
  what it promises)

- [ ] ⬜ **Task 1.3 (C)**: Run the optimise procedure in this self-install checkout and record each wrong path. RED
  test, then fix through the existing install-mode path resolution

- [ ] ⬜ **Task 1.4 (D)**: Confirm on a failed release-gate run that the other shards ran to the end. Fix in the
  release gate only (a fail-fast input to the shared `test-shards.yml`, default unchanged for `qa.yml`), keeping the
  final aggregate job's verdict

- [ ] ⬜ **Task 1.6 (F)**: RED test: a restore of a tracked file whose working copy is zero bytes is allowed, and a
  restore of a non-empty modified file is still denied. GREEN in `destructive_git`, alongside its other
  lossless-removal judgements

- [ ] ⬜ **Task 1.5 (E)**: RED test with the exact command shape, then narrow the discovery-idiom match so it is
  allowed, keeping the existing tests for real discovery commands red-to-green

- [ ] ⬜ **Task 1.7 (G)**: Find why the mapping (and the "Shell" job, which likely lints under the repository's own
  shellcheck config rather than the defaults this test uses) missed it. RED test in the mapping's own tests: a change
  to any file the asset lint test checks selects that test. GREEN in the mapping

- [ ] ⬜ **Task 1.8 (H)**: Plan 00587's fact-check found that a `cd` INSIDE a compound body (which must keep the
  body's later targets in doubt) is pinned only by a parser-level test. Add the containment-level deny test
  (`cd sub && for x in a; do cd /tmp; echo hi > x; done` denied) to `test_project_containment.py`; no code change
  expected

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: targeted QA per task, merge each to main, verify CI

## Success Criteria

- [ ] Each of A to G: a test that failed before the fix and passes after it, or recorded evidence that it does not
  reproduce
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` for each
  user-visible fix (A, B, C, E, F); D and G change CI only and have no release-bound consequence

## Delivery & Milestones

- (pending)
