# Plan 00362: client upgrade report — fix all known defects

**Status**: In Progress
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The next release is a stability push under the standing rule that a release
carries no known defect. This plan is the single ledger for that push. It
starts from a client project's report of eight issues met while upgrading
from v3.41.0 to v3.62.1 and running the config-optimisation pass (imported,
with reporter identifiers stripped, as
[REPORT-client-upgrade-v3.41-to-v3.62.1.md](REPORT-client-upgrade-v3.41-to-v3.62.1.md)),
and extends to every defect still recorded in a live plan, which the sweep in
Phase 2 enumerates.

Two of the client findings were verified against this repository before the
plan was filed: the v3.62.1 GitHub release carries no assets at all, so every
skill wrapper's self-bootstrap (`health-check.sh`, `daemon-cli.sh`,
`init-handlers.sh`) fails with a 404 on every install; and the config
validator has no notion of a handler key that no longer exists for its
event, so a stale `stop:` entry for the nitpick detectors passes as valid
while the detectors silently do not run.

## Goals

- Every item in the client report is fixed with a regression test, or is
  answered with a recorded reason and a message change that removes the
  confusion that produced the report.
- Every defect recorded in a live plan is fixed or explicitly ruled
  non-defect, so the release slate is clean.

## Non-Goals

- No feature work from the live plans: rescopes, ratchets and process
  changes stay in their own plans.
- No weakening of a deliberate guard to satisfy a report. Where a report
  disputes a rule that is deliberate (the `sed -n` deny), the fix is the
  message, not the rule, unless the owner rules otherwise.

## Tasks

### Phase 1: The client report

- [ ] ⬜ **Task 1.1** (report §1, HIGH): attach the bootstrap assets to the
  release as part of the pipeline so a release can never ship without them,
  and make the skill scripts fall back to the installed local wrapper when
  the manifest download fails instead of aborting.
- [ ] ⬜ **Task 1.2** (report §2, HIGH): `config-validate` and the upgrade
  config diff warn on a handler key that does not exist for its event, name
  the event it moved to where one is known (the two nitpick detectors →
  `pseudo_events.nitpick.handlers`), and the upgrade migrates those two
  automatically. Reconcile the reference config with the handler registry so
  every live handler is listed.
- [ ] ⬜ **Task 1.3** (report §3, MEDIUM): `echd-capture` is provisioned into
  client installs alongside the other deployed scripts, and the pipe_blocker
  guidance names its deployed absolute path only when it resolves, falling
  back to the redirect recipe otherwise.
- [ ] ⬜ **Task 1.4** (report §4, MEDIUM): `project_containment` recognises
  the harness's per-session scratchpad directory as an allowed write target,
  and its guidance says so.
- [ ] ⬜ **Task 1.5** (report §5, LOW): the `sed -n` deny is deliberate; the
  deny message says so explicitly and points at `Read` with offset/limit,
  and the handler doc's "read-only pipelines are allowed" sentence is
  corrected so it no longer contradicts the rule.
- [ ] ⬜ **Task 1.6** (report §6, HIGH): `tdd_enforcement` accepts a MIRROR
  test root (`{source_glob, test_dir, mirror: true}` in `test_path_map`, or
  `layout.test_dirs` entries) and checks every declared root, so a
  `tests/Small/<mirror>` layout can be enforced instead of disabled.
- [ ] ⬜ **Task 1.7** (report §7, LOW): the CLI accepts `validate-config` as an
  alias of `config-validate`, `config_path` defaults to the project config,
  and the deployed skill text is checked against the CLI's verb list by a
  test.
- [ ] ⬜ **Task 1.8** (report §8, LOW): the optimise procedure reads the
  config-changes manifests from the installed daemon tree (deploy them, or
  read them from the package), and the upgrader flags a still-enabled
  `daemon_stats` on a config that predates v3.40.

### Phase 2: Every other known defect in a live plan

- [ ] ⬜ **Task 2.1**: enumerate every defect recorded in the 25 live plans
  (the sweep report lands in this folder as `DEFECT-LEDGER.md`); add one task
  per defect below, each naming its plan and task ref.

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: full QA green on main after every merge; daemon
  restarted and RUNNING; the client-mode smoke (`scripts/dummy-client-repo.sh`)
  exercises the skill wrappers' bootstrap fallback and the tdd mirror root.

## Success Criteria

- [ ] Every Phase 1 and Phase 2 task is fixed with a test or answered with a
  recorded reason.
- [ ] `release-slate-check` reports a clean slate with no plan carrying a
  known defect.
- [ ] All QA checks passing.
- [ ] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/` callouts for each user-visible fix.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00362-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from the client report; two headline findings verified.
