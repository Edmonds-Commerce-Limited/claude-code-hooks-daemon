# Plan 00291: upgrade path hardening and guarded branch install

**Status**: Not Started
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

- [ ] ⬜ **Task 1.1**: TDD reproduction of `upgrade_version.sh` hard-failing
  when the client has config/forwarders but no venv and no daemon checkout
  (`stop_daemon_safe: venv_python parameter required` → rollback), then fix:
  a missing venv means there is no daemon to stop — skip the stop step
  cleanly rather than failing it.
- [ ] ⬜ **Task 1.2**: Decide and document the `upgrade_version.sh` vs
  `install_version.sh` boundary for an EXISTING-config/fresh-clone client
  (the canary had to guess); LLM-UPDATE.md gets one unambiguous instruction.
- [ ] ⬜ **Task 1.3**: Fix the cosmetic "Current version: unknown" in the
  upgrade flow's version capture when no prior checkout exists.

### Phase 2: Migration visibility (canary findings 3–4)

- [ ] ⬜ **Task 2.1**: `check-config-migrations`/`check-truth-changes` (and
  the install/upgrade steps that drive them) accept version arguments both
  with and without the `v` prefix; tests cover both spellings.
- [ ] ⬜ **Task 2.2**: Surface the config-migration advisory when
  `install_version.sh` retains an old-format config, instead of keeping it
  silently — the advisory already exists and works; wire it into this path.
- [ ] ⬜ **Task 2.3**: Branch installs read `CLAUDE/UPGRADES/UNRELEASED/`
  manifests as pending migrations (they are the migrations a branch install
  is ahead on); released-tag installs are unaffected.

### Phase 3: Guarded branch install (owner ruling)

- [ ] ⬜ **Task 3.1**: Design note in this folder recording the gate shape:
  env var with mandatory reason (e.g.
  `HOOKS_DAEMON_UNSAFE_TRACK_REF` + `..._BECAUSE`), refusal without both,
  warning banner text, and the explicit list of places that must NOT mention
  it (LLM-INSTALL.md, LLM-UPDATE.md, README, HOOKS-DAEMON.md).
- [ ] ⬜ **Task 3.2**: Implement in the upgrade tooling: gate honoured only
  when both variables are set; target ref checked out without the
  `v`-normalisation; loud banner; refusal of the positional-arg spelling for
  branch names preserved (a bare `main` must keep failing).
- [ ] ⬜ **Task 3.3**: Version stamping: a branch install reports
  `vX.Y.Z+<branch>.<shortsha>`; `status` shows it; `version_check` flags it
  as a non-release install every session and never reports it "up to date".
- [ ] ⬜ **Task 3.4**: Acceptance coverage in the dummy-client harness:
  gated install succeeds with both vars, refuses with either missing, banner
  and stamp asserted.

### Phase 4: Canary integration and verification

- [ ] ⬜ **Task 4.1**: Re-run the php-qa-ci canary end-to-end through the
  now-fixed documented route using the guarded gate; the run must need zero
  manual bypasses. Update the canary report with the delta.
- [ ] ⬜ **Task 4.2**: Full QA green; daemon restart verified; UPGRADES
  manifests updated for any config surface added.

## Success Criteria

- [ ] Fresh-clone client upgrade succeeds via the documented route with no
  manual fallback (proved by the re-run canary).
- [ ] Every clause of the owner ruling is enforced by test: non-obvious,
  env-gated with reason, loudly warned, version-stamped, refused as current
  by version_check, absent from user-facing docs.
- [ ] UNRELEASED manifests visible to branch installs; `v`-prefix accepted
  everywhere the docs produce it; old-config advisory surfaces on install.
- [ ] Full QA passes.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
