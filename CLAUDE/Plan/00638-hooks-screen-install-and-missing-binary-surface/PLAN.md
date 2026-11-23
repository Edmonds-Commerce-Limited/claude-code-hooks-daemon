# Plan 00638: hooks screen install and missing binary surface

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00523 (rate-limit dialog answer, and the screen focus hold) needs the
`hooks-screen` binary at `<project>/untracked/bin/hooks-screen`. The release
workflow `.github/workflows/release-assets.yml` already publishes
`hooks-screen-<triple>` (x86_64 and aarch64 musl) with `SHA256SUMS` and
provenance, but nothing installs it on a client seat. Today the operator installs
it by hand (CLAUDE/development/CcySupervisor.md, "Operator install"). Context from
Plan 00630's coordinator line: a fedora-desktop play downloads it from the v3.77.0
release as a stop-gap, and this plan's route replaces that play in the release
after v3.77.0.

A missing binary fails open: `ScreenBuffer._failed` in
`.claude/ccy/claude-supervise.py` logs `screen check failed open: <reason>` once
per distinct reason to the supervisor decision log. Whether anything beyond
`decision.log` shows it to a person is unverified; a person who enabled a feature
that needs the binary gets no visible notice.

Dedupe: `bin/hooks-daemon find-plan hooks-screen` and `find-plan screen` match only
Completed Plan 00569 (host-arch build target), which covers neither install nor
surfacing. The dedupe scout was not available when this was filed.

## Goals

- (a) `hooks-daemon` upgrade/install deploys the right `hooks-screen-<triple>`
  from the release, verified, to `<project>/untracked/bin/hooks-screen` mode 0755.
- (b) A missing binary is visible to a person when a feature needing it is on.

## Non-Goals

- Building hooks-screen on the client (`screen/build.sh` stays the dev route).
- Changing the lookup order in `resolve_screen_binary`.

## Tasks

### Phase 1: Lasting install route (a), tests first

Reuse the download machinery in
`src/claude_code_hooks_daemon/install/relay_deploy.py` (`deploy_relay_from_download`
near line 460, `_release_asset_url`, `_parse_sha256sums`, `_default_fetch`,
`SHA256SUMS_ASSET_NAME`). The ccy deploy that copies `.claude/ccy/` is
`deploy_ccy_supervisor_if_enabled` in
`src/claude_code_hooks_daemon/install/ccy_supervisor.py:178`; confirm the call
site for the screen step when implementing.

- [ ] ⬜ **Task 1.1 (red)**: tests in `tests/unit/install/` for a new
  `deploy_screen_from_download`: right triple for x86_64 and aarch64; checksum
  mismatch refuses and leaves no file; unsupported arch skips with a note;
  already-installed same-version is a no-op; download failure returns an advisory
  and does not raise; never a partial file (temp file in the same directory,
  verify, atomic rename).
- [ ] ⬜ **Task 1.2 (green)**: implement it, verifying only the asset's own
  `SHA256SUMS` line, installing mode 0755, recording the deployed version in a
  marker beside the binary (as relay_deploy does for its digest).
- [ ] ⬜ **Task 1.3**: call it from the ccy deploy; failure is a non-fatal
  advisory in the upgrade/install output.
- [ ] ⬜ **Task 1.4**: update CcySupervisor.md "Operator install" to say the deploy
  installs it and the manual `gh release download` steps are the fallback.

### Phase 2: Visible missing-binary surface (b), tests first

- [ ] ⬜ **Task 2.1 (read-only first)**: trace how `ScreenBuffer._failed` output
  reaches a person today (decision.log only is the working belief, unverified).
  Name the existing surface to reuse: candidates are the
  `ccy_supervisor_integrity` SessionStart handler, the `supervisor_indicator`
  status-line handler, or the ccy host's visible notice.
- [ ] ⬜ **Task 2.2 (red)**: with a screen-needing feature enabled
  (`CCY_RATE_LIMIT_DIALOG` not off, or `CCY_FOCUS_HOLD=1`) and no resolvable
  binary, the chosen surface emits an advisory naming the fix; nothing when the
  feature is off or the binary is present.
- [ ] ⬜ **Task 2.3 (green)**: implement it on the surface named in 2.1.

### Phase 3: QA

- [ ] ⬜ **Task 3.1**: targeted QA, then hand to the coordinator for the full gate.

## Success Criteria

- [ ] Phase 1 and 2 red tests written first and green after implementation.
- [ ] A client upgrade installs a verified hooks-screen with no manual step.
- [ ] A person is told when a needed hooks-screen is missing.
- [ ] Holding-area: record the release-bound change (the deploy installs
  hooks-screen) in the pending-release holding area, or state why none.

## Delivery & Milestones

- Parent context: Plan 00523 (rate-limit dialog), Plan 00630 (coordinator line).
