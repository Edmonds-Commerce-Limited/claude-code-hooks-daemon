# Plan 00476: release through a pr with ci tagging

**Status**: In Progress
**Created**: 2026-09-30
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #107 (the owner's restatement, folded in as Design items 5 to 7)

## Overview

**Owner direction:** a release branch exists for QA. It is proposed as a pull
request, and the pull request runs the whole QA gate in CI. The actual release
stays a local process with the daemon live: acceptance testing, tagging and
publishing run from the session, as `/release` does today, once the release
branch's CI gate is green.

Why. Today `/release` runs the whole gate locally on the main thread, holding the
host lock for the entire suite, then tags and publishes from the session. Two
defects of v3.67.0 came from that: the tag carried a stale UNRELEASED index
because nothing ran between Step 6 and the tag (ledger 00474 N263), and the
release body only failed its size limit after the tag was pushed (N262). A pull
request gate tests the exact commit that gets tagged, and moves the one full run
off this host. It is also the natural home for Plan 00475's rule that the full
gate runs only at release preparation.

Starts after Plan 00475's first batch finishes (small-batches rule).

## Design

1. **Prepare (in session, `/release`):** create a release branch from `main`,
   bump the version, assemble the release notes and changelog section from the
   `CLAUDE/UPGRADES/UNRELEASED/release-notes/` callouts and the merges since the
   last tag, move the UNRELEASED upgrade tasks, and run the Opus documentation
   review and the upgrade-guide gate. Push and open the pull request.
2. **QA gate (CI, on the pull request):** run `llm_qa.py all` across the
   supported Pythons, including the checks that need a live daemon. CI already
   starts a daemon and fetches full history. This replaces the local full gate,
   so the host never runs the whole suite.
3. **Release (in session, local daemon):** once the pull request's CI is green,
   `/release` resumes. It runs the acceptance tests (they need real tool calls
   in a Claude session, so they cannot move to CI), merges the pull request,
   tags the merge commit, builds the body with
   `scripts/release/build_github_release_body.py`, and publishes the GitHub
   release with its assets. `/release` stays the human gate, as today.
4. **The tagged commit is the gated commit:** merges to `main` are frozen while
   a release pull request is open. If `main` moves anyway, the release branch is
   updated and CI re-runs before tagging.
5. **Parallel jobs (#107):** the release pull request's gate runs one job per
   supported Python, sharded where a job is long, so wall-clock time stays close
   to today's local run. Measured in Task 1.2 against the local timing report.
6. **Performance sweeps in their own job (#107, ledger 00474 N376):** the sweeps
   that fail under the full gate's own load run in a CI job with nothing else on
   the runner. Their thresholds are never loosened.
7. **The CI run is the recorded QA result (#107):** `untracked/release-state.json`
   records the pull request's CI run (id and head commit) as the release's QA
   result, and resuming `/release` checks that the head commit is the one CI
   passed.

Routine work is already targeted-only (Plan 00475); #107 restates that rule and
it needs no new task here.

**Not included:** whole-codebase mutation testing. The repository has no
mutation-testing tooling, and across the whole suite it would far exceed any
pull request check. If wanted, it gets its own plan, starting with changed
modules only.

## Goals

- A release is only tagged on a commit whose release pull request passed the
  whole gate in CI.
- The whole gate runs in CI, not on this host.
- Acceptance testing, tagging and publishing stay local, in `/release`.

## Non-Goals

- Mutation testing.
- Tagging or publishing from CI.
- Changing the tag naming or version scheme.

## Tasks

### Phase 1: Prove the gate runs in CI

- [x] ✅ **Task 1.1**: Run each of the 43 `llm_qa.py` checks on a CI runner in a
  trial workflow. List the ones that need changes to run there. Delivered:
  `subagent-reports/261022-task-1.1-trial-workflow-sonnet.md`; 42 of 43 ran
  unchanged; `tests` failed on the daemon idling out, and the keepalive added to
  the gate's test jobs held in run 39728713370.
- [x] ✅ **Task 1.2**: Time each check's job on the runner against the local
  `llm_qa.py` timing summary, and choose the per-Python jobs and shards from it
  (Design 5). Delivered: `subagent-reports/261022-task-1.1-1.2-findings-sonnet.md`;
  4 check groups and 8 test jobs in `release-gate.yml`, drawing on the 7 shards
  in `scripts/qa/test_shards.yaml`.

### Phase 2: Workflows

- [x] ✅ **Task 2.1**: A release pull request workflow that runs the whole gate,
  one job per Python, sharded where measured to need it (Design 5). Delivered:
  `.github/workflows/release-gate.yml`; green on main in run 39728713370.
- [x] ✅ **Task 2.2**: A separate performance-sweep job (Design 6). Delivered:
  `perf_sweep` marker on the 7 `scaled_cpu_seconds` tests (11 cases), deselected
  from the fallback and matrix steps, run alone by the `perf-sweep` CI job.
- [x] ✅ **Task 2.3**: The release state file records the CI run and `/release`
  checks it on resume (Design 7). Delivered: optional `ci` record in the state
  file and `scripts/release/check_release_ci.py` (strict schema, live `gh run view` check behind a seam, one-line named failure, exit 1).

### Phase 3: Procedure

- [x] ✅ **Task 3.1**: Rewrite `RELEASING.md`, the release skill and the release
  agent: prepare, open the pull request, wait for CI green, then acceptance
  tests, merge, tag and publish locally. Delivered: `RELEASING.md` Steps 1b,
  7.1, 8 (8a/8b/8c), 13 and 14 rewritten, step numbers otherwise kept, a merge
  freeze section; the skill, its `invoke.sh` and the agent now point at it.
- [x] ✅ **Task 3.2**: A freeze on merges to `main` while a release pull request
  is open. Delivered: project handler `release_merge_freeze` (R-RELEASE-MERGE-FREEZE)
  denies `git merge` on main, `git push` to main and `gh pr merge` of any pull
  request but the one in the state file's `ci.pr_number`; a malformed state file
  fails closed. Task 3.1 must document the freeze in `RELEASING.md`.

## Success Criteria

- [ ] A release goes from `/release` to a published GitHub release with no
  local full gate, and its tag is on a commit the pull request's CI passed.

## Delivery & Milestones

- All tasks merged to main (`c7637cf1c` Task 2.1, `1ad2e3618` Task 3.1); the
  release-gate workflow ran green on main in run 39728713370.
- Open: the success criterion needs the first real release through the new
  procedure, which only a human-invoked `/release` can start.
