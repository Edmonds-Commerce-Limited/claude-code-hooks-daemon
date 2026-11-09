# Plan 00576: hotfix release fast path

**Status**: Complete
**Created**: 2026-11-09
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded

## Overview

The emergency patch release v3.73.1 took far too long because the release
pipeline has one speed: every patch, however urgent, runs the slate gate's
human stop, the Housekeeping phase, the Claude Code changelog review, the Opus
documentation review, a whole-diff code review and the full acceptance
playbook. The owner chose four changes to give an emergency patch a shorter
path without dropping any gate that protects what is published.

The kept gates are the ones that judge the published artefact: the release
pull request, the full `Release gate` CI run (the whole test suite), the
start-up budget gate, the merge freeze, Step 13's CI verification, tagging and
publishing. What the fast path drops is work whose value is scope-wide
(housekeeping, changelog review, documentation review, whole-diff review,
full playbook) rather than about the hotfix itself.

Two smaller defects slowed the same release and are fixed alongside: an
advise-severity plan-QA finding (journal freshness) failed the CI gate, and a
superseded `Release gate` run was not shown to be cancelled by a test.

## Goals

- `/release hotfix` and `/release X.Y.Z hotfix` run a documented fast path
  ("Hotfix fast path" in `CLAUDE/development/RELEASING.md`), printed by
  `invoke.sh`, recorded as `"mode": "hotfix"` in the state file, and named by
  the `release_blocker` stop guard so a resumed session follows the same path.
- Advise-severity `plan_qa` / `docs_qa` findings never fail a QA check, in
  the release gate or `qa.yml`; block-severity findings still do.
- `release-gate.yml`'s concurrency group (cancel superseded runs) is pinned by
  a test.

## Non-Goals

- No change to the kept gates listed above, to `release_merge_freeze`, or to
  `check_release_ci.py`.
- No refactor of unrelated pipeline steps; the standard pipeline is unchanged.

## Design

1. **Hotfix mode.** `invoke.sh` accepts `hotfix` as either argument
   (`hotfix`, `X.Y.Z hotfix`); the bump is a patch. In that mode it passes
   `--accept` to `release-slate-check` (report still printed), tells the
   orchestrator to write `"mode": "hotfix"`, and prints the fast-path step
   list. RELEASING.md's "Hotfix fast path" section owns the step list: skip
   1H and 1c, skip the Step 7 Opus review (release agent writes a short
   changelog / notes entry; Step 6 UNRELEASED moves unchanged), Step 10
   reviews only the hotfix range (findings outside it are filed as plans),
   Step 12 runs 12.0 plus targeted tests for changed handlers.
2. **State file.** No code validates the top-level keys strictly (only the
   `ci` record, in `check_release_ci.py`). The reader that tells a resumed
   session what to do is `release_blocker`'s deny message, so it names the
   mode: `hotfix` points at the fast path and states its acceptance scope;
   an unrecognised mode is named and the standard pipeline is assumed.
3. **Advisories never fail.** `scripts/qa/run_corpus_qa.py` set
   `passed: not findings` and exited 1 on any finding. It now passes and
   exits 0 unless a block-severity finding (or a finding with no recognised
   severity, fail closed) is present. `CLAUDE/QA.md` updated to match.
4. **Stale CI.** `release-gate.yml` already carries
   `concurrency: {group: release-gate-<PR or ref>, cancel-in-progress: true}`
   (Plan 00476); a test now asserts it.

## Tasks

### Phase 1: Advisories never fail CI

- [x] ✅ **Task 1.1**: RED tests in `tests/unit/qa/test_run_corpus_qa.py`
  (advise-only passes and exits 0; block fails and exits 1; unknown
  severity fails)
- [x] ✅ **Task 1.2**: GREEN in `scripts/qa/run_corpus_qa.py`; update
  `CLAUDE/QA.md`

### Phase 2: Stale CI

- [x] ✅ **Task 2.1**: test asserting the concurrency block in
  `tests/unit/qa/test_release_gate_layout.py`

### Phase 3: Hotfix mode

- [x] ✅ **Task 3.1**: RED tests for `invoke.sh` hotfix output and
  `release_blocker` mode naming
- [x] ✅ **Task 3.2**: GREEN: `invoke.sh`, `SKILL.md`, `release_blocker.py`
- [x] ✅ **Task 3.3**: RELEASING.md "Hotfix fast path" section + state-file
  `mode` field
- [x] ✅ **Task 3.4**: release-notes callout in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`

### Phase 4: Delivery

- [x] ✅ **Task 4.1**: targeted QA (`llm_qa.py changed --range`), push, PR
- [x] ✅ **Task 4.2**: find out why superseded release-gate run 42598705633
  seemed not to be cancelled (journal 11:27: the concurrency group did cancel
  it; the red-run-keeps-running gap is out of scope)

## Success Criteria

- [x] An advise-only corpus report passes and a block report fails (tests)
- [x] A test asserts `release-gate.yml`'s cancel-in-progress concurrency group
- [x] `invoke.sh hotfix` / `invoke.sh X.Y.Z hotfix` print the fast path
  and `--accept`; the standard invocation output is unchanged (tests)
- [x] `release_blocker` names hotfix mode from the state file (tests)
- [x] RELEASING.md has a "Hotfix fast path" section with the step list
- [x] Release-bound consequence recorded in the holding area:
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/013-hotfix-release-fast-path.md`
- [x] Targeted QA green (41/42, then the one failure fixed and re-run green);
  PR #190 merged to main with green CI

## Delivery & Milestones

- PR: #190 ([fact-check](subagent-reports/261109-fact-check-plan-00576.md): 18 verified, 0 refuted)
- Merged: `8bfcad71f` (every required check green; the non-blocking arm64 leg was still pending)
- Release-bound: release note 013 ships with the next release
