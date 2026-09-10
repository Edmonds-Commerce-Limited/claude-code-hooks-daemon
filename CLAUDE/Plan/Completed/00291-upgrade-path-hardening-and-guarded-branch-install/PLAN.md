# Plan 00291: upgrade path hardening and guarded branch install

**Status**: Complete
**Created**: 2026-08-30
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The php-qa-ci canary migration (report:
`untracked/reports/canary-php-qa-ci-upgrade-26-08-30.md`, session 2026-08-30)
exercised the real client upgrade path — a fresh clone of a genuine v3.41.0
client upgraded to current main — and surfaced upgrade-tooling defects that
only a real client in a fresh-clone state could reveal. The upgrade ultimately
succeeded and the daemon behaved perfectly, but the documented route failed
and had to be bypassed. This plan fixes the path itself.

It also delivers the **guarded branch-install mechanism** the canary needed:
a first-party-only facility to install/upgrade to a branch (main) instead of a
release tag. **Owner ruling (2026-08-30, binding)**: "supporting main as a
version should not become something normal users can do, its really only for
us — so whatever mechanism needs to be something guarded and non obvious and
with clear warnings." The mechanism must therefore have no positional-arg
spelling, no mention in user-facing install/update docs, an environment-variable
gate carrying a mandatory reason (the `MUST_..._BECAUSE` convention), a loud
warning banner at install time, and a version stamp (`vX.Y.Z+<branch>.<sha>`)
that `status`/`version_check` surface every session and refuse to treat as a
current release.

Related but out of scope here: Plan 00176 (settings.json merge preservation)
proceeds independently; the dedupe scout confirmed no live-plan overlap.

**Canary policy (owner ruling, 2026-08-30)**: the php-qa-ci clone at
`untracked/repos/php-qa-ci` is a **persistent, test-only canary**. Every run
starts from a pristine state (delete + re-clone, or an equivalent full reset
to origin HEAD) and NO run there is ever a real upgrade — nothing is committed
or pushed from the canary. The REAL php-qa-ci upgrade happens in a separate
agent thread, as the final confirmation step AFTER a release ships.

## Goals

- The documented upgrade route works from the fresh-clone client state (no
  venv, no daemon code on disk) without falling back to manual steps.
- A branch-tracking canary install can see and apply UNRELEASED
  config-changes/truth-changes manifests.
- A many-versions-old config triggers the existing migration advisory during
  install/upgrade instead of being kept silently.
- Version-string handling is consistent: the CLIs accept what the docs
  produce.
- The guarded branch-install mechanism exists, satisfies every clause of the
  owner ruling above, and is exercised by the php-qa-ci canary as its standing
  upgrade route.

## Non-Goals

- No user-facing branch/ref feature: no `--ref` flag, no docs section, no
  positional-arg support. The gate stays deliberately non-obvious.
- No settings.json merge-strategy work (Plan 00176's scope).
- No changes to release tagging or the release pipeline itself (human-gated
  `/release` flow is untouched).

## Tasks

### Phase 1: Fix the fresh-clone upgrade failure (canary finding 1, HIGH)

- [x] ✅ **Task 1.1**: TDD reproduction of `upgrade_version.sh` hard-failing
  when the client has config/forwarders but no venv and no daemon checkout
  (`stop_daemon_safe: venv_python parameter required` → rollback), then fix:
  a missing venv means there is no daemon to stop — skip the stop step
  cleanly rather than failing it. Delivered under Plan 00362 Task 2.2:
  `tests/integration/test_upgrade_fresh_clone_stop_step.py` runs the real
  Step 4 block under `set -euo pipefail` with an empty `VENV_PYTHON`.
- [x] ✅ **Task 1.2**: Decide and document the `upgrade_version.sh` vs
  `install_version.sh` boundary for an EXISTING-config/fresh-clone client
  (the canary had to guess); LLM-UPDATE.md gets one unambiguous instruction.
  Decision: a config means an existing install, so the update route applies
  and `upgrade.sh` clones the missing daemon checkout itself (`af8dc453`).
- [x] ✅ **Task 1.3**: Fix the cosmetic "Current version: unknown" in the
  upgrade flow's version capture when no prior checkout exists. Layer 1
  hands the previous version to Layer 2 (from the committed HOOKS-DAEMON.md
  when it cloned the checkout); Layer 2 reads version.py directly when there
  is no venv (`af8dc453`).

### Phase 2: Migration visibility (canary findings 3–4)

- [x] ✅ **Task 2.1**: `check-config-migrations`/`check-truth-changes` (and
  the install/upgrade steps that drive them) accept version arguments both
  with and without the `v` prefix; tests cover both spellings. Delivered
  under Plan 00362 Task 2.2: one shared parser
  (`install/version_parse.py`) behind the truth-changes, config-migrations,
  release-notes and breaking-changes loaders;
  `tests/unit/install/test_version_parse.py`.
- [x] ✅ **Task 2.2**: Surface the config-migration advisory when
  `install_version.sh` retains an old-format config, instead of keeping it
  silently — the advisory already exists and works; wire it into this path.
  Delivered under Plan 00362 Task 2.2: reproduced by running the real Step 7
  block against a pre-v3.40 config (only "keeping existing configuration"
  printed); Step 7 now runs the advisory from the earliest known manifest,
  says which baseline it assumed, and never aborts the install.
  `tests/integration/test_install_version_retained_config_advisory.py`.
- [x] ✅ **Task 2.3**: Branch installs read `CLAUDE/UPGRADES/UNRELEASED/`
  manifests as pending migrations (they are the migrations a branch install
  is ahead on); released-tag installs are unaffected. Both loaders take
  `include_unreleased`, automatic from the install stamp;
  `--include-unreleased` on both CLI commands (`af8dc453`).

### Phase 3: Guarded branch install (owner ruling)

- [x] ✅ **Task 3.1**: Design note in this folder recording the gate shape:
  env var with mandatory reason (e.g.
  `HOOKS_DAEMON_UNSAFE_TRACK_REF` + `..._BECAUSE`), refusal without both,
  warning banner text, and the explicit list of places that must NOT mention
  it (LLM-INSTALL.md, LLM-UPDATE.md, README, HOOKS-DAEMON.md).
  [GUARDED-BRANCH-INSTALL.md](GUARDED-BRANCH-INSTALL.md) (`af8dc453`).
- [x] ✅ **Task 3.2**: Implement in the upgrade tooling: gate honoured only
  when both variables are set; target ref checked out without the
  `v`-normalisation; loud banner; refusal of the positional-arg spelling for
  branch names preserved (a bare `main` must keep failing).
  `scripts/install/branch_install.sh`, Layer 1 and Layer 2 (`af8dc453`).
- [x] ✅ **Task 3.3**: Version stamping: a branch install reports
  `vX.Y.Z+<branch>.<shortsha>`; `status` shows it; `version_check` flags it
  as a non-release install every session and never reports it "up to date".
  `install/install_stamp.py` is the one reader (`af8dc453`).
- [x] ✅ **Task 3.4**: Acceptance coverage in the dummy-client harness:
  gated install succeeds with both vars, refuses with either missing, banner
  and stamp asserted. `tests/integration/test_branch_install_gate.py` and the
  slow `tests/acceptance/test_guarded_branch_install.py` against a real
  client install (`af8dc453`, foreign-cwd reproduction `4b77b327`).

### Phase 4: Canary integration and verification

- [x] ✅ **Task 4.1**: Re-run the php-qa-ci canary end-to-end through the
  now-fixed documented route using the guarded gate; the run must need zero
  manual bypasses. Per the canary policy above: start pristine
  (re-clone/full reset), commit nothing in the canary. Update the canary
  report with the delta. Three pristine runs; runs 1 and 2 exposed two
  client-breaking defects, fixed in `4b77b327` (Layer 2 anchored at the
  project root) and `03eef02f` (init.sh follows the PID file into the
  runtime dir); run 3 clean through the real forwarders. Report:
  `untracked/reports/canary-php-qa-ci-upgrade-26-09-09.md`.
- [x] ✅ **Task 4.2**: Full QA green; daemon restart verified; UPGRADES
  manifests updated for any config surface added. No config/truth-changes
  surface was added (Task 4.2 decision, `af8dc453`), so those two manifests
  stay empty; release-notes callouts 14 and 15 are the holding-area record.
  QA found two real issues introduced by this plan's own work (a magic
  timeout constant, and `print_branch_install_banner` writing its warning to
  stdout instead of stderr — the v3.10.0 SEV-1 capture-corruption pattern —
  plus three drifted `error_hiding_exclusions.json` line numbers from the
  intervening edits); fixed, and `llm_qa.py all` is now 26/26 PASSED. Daemon
  restarted and verified RUNNING in this worktree.

## Success Criteria

- [x] ✅ Fresh-clone client upgrade succeeds via the documented route with no
  manual fallback (proved by the re-run canary, run 3 clean).
- [x] ✅ Every clause of the owner ruling is enforced by test: non-obvious,
  env-gated with reason, loudly warned (now provably to stderr, never stdout),
  version-stamped, refused as current by version_check, absent from
  user-facing docs.
- [x] ✅ UNRELEASED manifests visible to branch installs; `v`-prefix accepted
  everywhere the docs produce it; old-config advisory surfaces on install.
- [x] ✅ Every release-bound consequence is in the pending-release holding
  area: a release-notes callout exists for every user-visible fix this plan
  shipped — callout 14 (the upgrade-path fixes) and callout 15 (the two
  canary-found bugs), both staged under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [x] ✅ Full QA passes (`llm_qa.py all`: 26/26 PASSED).
- [x] ✅ Plan folder moved to `Completed/`, the README row/stats updated, and
  the status header flipped to `Complete` in one commit on `main` after the
  branch merge (`f0896ced`).

## Delivery & Milestones

- `a0ac90f5` — Tasks 1.1, 2.1 and 2.2 delivered under Plan 00362 Task 2.2
  (fresh-clone stop step, shared v-tolerant version parser, retained-config
  migration advisory).
