# Plan 00586: five small defects, verify then fix

**Status**: Complete
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

- [x] ✅ **Task 1.1 (A)**: Reproduced: a probe over every `added` handler key in the manifests (186 keys across the
  61 manifests `load_manifests_between` reads, the first version excluded as the from-version) found 9 not
  registered for their event now. Seven are gone and were being recommended: `plan_completion_advisor`,
  `task_tdd_advisor`, `hedging_language_detector`, `working_directory`, `current_time`, `upgrade_approval_guard`
  and `yolo_container_detection`. The other two stay suggested on purpose: the placeholder `handlers.<event>.<handler>.scope`,
  and `branch_count_advisor`, a live key alias of `branch_sweep` (`HANDLER_KEY_ALIASES`). Plan 00420 is Not Started
  and does not cover it. RED tests in `test_config_migrations_gone_handlers.py` (3 failed, 4 controls passed);
  GREEN with `handler_key_is_gone` in `handler_key_audit.py`, applied to `added` and `changed` entries in
  `generate_migration_advisory`. A name the audit does not classify (retired, relocated, wrong event) stays
  suggested, since it may be a project handler. Release note 113

- [x] ✅ **Task 1.2 (B)**: Reproduced: the two readers disagreed (`core/relevance.py` treated `[]` as an empty set,
  `core/apply_once.py` treats it as unset). The enforcing reader fails safe (every language guard stays on), so the
  relevance review now reads `[]` as unset too. RED test
  `test_an_empty_declaration_is_unset_so_detection_applies` failed with `frozenset()`, green after the fix; release
  note 112

- [x] ✅ **Task 1.3 (C)**: Ran the script in this self-install checkout: `Manifests` and `Run state` printed
  `.claude/hooks-daemon/CLAUDE/UPGRADES/config-changes` and `.claude/hooks-daemon/untracked/...`, neither of which
  exists. Cause: `.claude/hooks-daemon/bin/hooks-daemon` is a link to the project's own wrapper, so the script's
  client-install probe matched first. RED test `TestALinkedSelfInstallResolvesToTheProjectRoot` (a fixture with that
  link, which the existing self-install fixture lacked) failed; GREEN by testing first whether the client-path wrapper
  resolves to the project's own. `optimise.md`'s three reference paths (the config-changes manifests and two
  `docs/guides/` references, which named a client-only `.claude/hooks-daemon/` tree) now name the printed daemon
  directory. Deployed skill copies synced
  (34 related tests pass). Release note 114

- [x] ✅ **Task 1.4 (D)**: Closed as designed, no change. Confirmed: the last 30 `release-gate.yml` runs were all
  skipped (none was a release pull request), so no gate run has failed to read; the same shared `test-shards.yml`
  ran as the full-suite fallback of PR 276's CI (run 45739790836), where the integration shard failed at 12 minutes
  and the unit and integration-slow legs ran on regardless, which is `fail-fast: false` doing what `qa.yml` says it
  is for. Decision against a fail-fast input: it would cancel only the sibling legs of the `tests` job, never the
  separate `checks` and `perf-sweep` jobs, so it saves part of the runner minutes; and a release run takes about 40
  minutes, so a failure hidden by the cancel costs a whole further cycle to find. Reopen if a release run is seen
  burning runners after the gate is already red and the saving is worth the hidden failures

- [x] ✅ **Task 1.6 (F)**: RED test: a restore of a tracked file whose working copy is zero bytes is allowed, and a
  restore of a non-empty modified file is still denied. GREEN in `destructive_git`, alongside its other
  lossless-removal judgements. Done: `GIT_RESTORE` joined `_LOSSLESS_WHEN_PROVEN`; `_restore_note` allows a restore
  only when every named path is a literal, tracked, regular, zero-byte file (globs, directories, symlinks,
  `--source`, `-p`, substitutions and anything with content stay denied). Tests
  `test_destructive_git_restore_empty.py`; release note 115

- [x] ✅ **Task 1.5 (E)**: Does not reproduce; closed with the evidence and no change. The original command was
  never recorded, so 19 shapes were run through `PlanNumberHelperHandler.matches` on main: an `ls` of a plan
  folder, its `JOURNAL/`, `Completed/` or a glob, and `git status`, each piped to `awk` and chained (`&&` or `;`,
  either order) with `git add CLAUDE/Plan/...`, are all allowed. The only denied shape is a real discovery
  (`ls CLAUDE/Plan | awk -F- '{print $1}' | sort | tail -1`), which is correct. GitHub #151's narrowing (a
  listing inside one numbered folder is allowed) already covers the plan-folder shapes. If the shape recurs,
  record the exact command and reopen

- [x] ✅ **Task 1.7 (G)**: Cause: `scripts/qa/changed_tests_map.yaml` mapped `*.sh` to shellcheck and the bash 3.2
  scan only, and nothing named `test_client_owned_asset_lint.py`, which reads its files through the
  `CLIENT_OWNED_ASSETS` manifest, so no import or name links an asset to it. RED test
  `test_every_client_owned_asset_selects_the_asset_lint_test` (reads the manifest, so a new asset cannot be missed)
  failed on `init.sh`; GREEN with one rule per manifest source (108 tests pass). The "Shell" job was not changed: it
  scans only `scripts/` and `src/`, so the root `provision.sh` and `init.sh` are never shellchecked there, and
  `run_shell_check.sh` does not fail on info-level findings, which is the level SC2030 and SC2031 report at

- [x] ✅ **Task 1.8 (H)**: Plan 00587's fact-check found that a `cd` INSIDE a compound body (which must keep the
  body's later targets in doubt) is pinned only by a parser-level test. Added the containment-level deny tests
  (`cd sub && for x in a; do cd /tmp; echo hi > x; done` and the `while`, `if` and `{ }` forms, plus an in-project
  twin that stays allowed) to `test_project_containment.py`; all pass on main, so no code change was needed

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: targeted QA per task, merge each to main, verify CI. Merged: B PR 271, H PR 272, G PR 273,
  A PR 274, C PR 275, F PR 276 (each with an independent review); D and E closed without a change

## Success Criteria

- [x] Each of A to H: a test that failed before the fix and passes after it, or recorded evidence that it does not
  reproduce (E and D are the recorded-evidence cases)
- [x] Release-bound consequence recorded: callouts in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` 112 (B), 113 (A),
  114 (C) and 115 (F); E and D changed nothing, and G, H changed CI mapping and tests only, so they have no
  release-bound consequence

## Delivery & Milestones

- 2026-11-26: all tasks complete; merge commits `b491a422e` (B), `1c66dfd6d` (H), `eb5e9784a` (G), `97886819a` (A),
  `068009f7f` (C), `60fcb2678` (F)
