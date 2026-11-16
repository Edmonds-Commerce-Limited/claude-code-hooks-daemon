# Plan 00608: provision sh provisions the relay binary

**Status**: In Progress
**Created**: 2026-11-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`.claude/provision.sh` (the tracked symlink to the root `provision.sh`, which is the single source) builds a fresh checkout's daemon clone through `scripts/venv_bootstrap.sh repair` and starts the daemon, but it never provisions the Rust relay binary. Only `scripts/install_version.sh` and `scripts/upgrade_version.sh` run `provision_relay_binary` (`scripts/install/relay_provision.sh`). A provisioned clone therefore has the relay on by default (Plan 00529, `relay_source: auto`) but no binary, and runs every hook on the fallback transport. Seen on an aarch64 box, where the release does ship the aarch64 asset, so it is not an asset gap. Finding: `CLAUDE/Plan/00594-branch-lifecycle-and-branch-tip-channel/JOURNAL/2026-11-15/211946Z-finding-99c05b.md`.

The fix makes provision run the same helper step, in the foreground, after the venv is built and the clone is at the expected version, including the already-at-version path when the binary is missing or defective. It warns and never aborts. A `--background` run never builds or downloads; it reports the missing relay and names `hooks-daemon transport on`.

A second question rode along: on that box the session-start relay repair left no state file and no log. That is investigated read-only and recorded in the journal.

## Goals

- A foreground provision of a fresh checkout leaves the relay binary in place (or a loud banner and a successful provision).
- The already-at-version path provisions a missing or defective binary, and leaves a usable one alone.
- A sync to another tag provisions the relay for the new tag, outside every rollback path.
- `--background` reports a missing relay and builds nothing.
- `relay_enabled: false` does nothing.

## Non-Goals

- Changing install or upgrade, or the relay build and download logic.
- Making a background run build or download anything.

## Tasks

### Phase 1: provision runs the relay step

- [x] ✅ **Task 1.1**: Tests first: stand-ins for the relay CLI and the forwarder generator in the provision sandbox, and cases for fresh, at-version, stale venv, background, sync, helper missing, banner, unexpected exit, regeneration failure.
- [x] ✅ **Task 1.2**: Add `relay_deploy --check` (read-only: 0 disabled or usable, 3 missing or defective), with unit tests.
- [x] ✅ **Task 1.3**: Wire the step into `provision.sh` at the three call sites, reusing `relay_provision.sh`; closing lines repeat a failure and report regenerated tracked forwarders truthfully.
- [x] ✅ **Task 1.4**: Release note.

### Phase 2: the silent repair

- [x] ✅ **Task 2.1**: Read-only investigation of why the session-start relay repair left no state or log. Not reproducible; the finding and the open question for the box are in this plan's JOURNAL (2026-11-15 finding entry). No code change.

### Phase 3: follow-ups from the no-trace investigation

- [ ] **Task 3.1**: The relay repair also starts where the daemon starts (deferred startup step), once per cause, detached, failures logged; tests first; release note 080.
- [x] ✅ **Task 3.2**: Log the silent mkdir/open failure branch in `relay_repair.py`; release note 079.
- [ ] **Task 3.3**: `hooks-daemon status` prints the relay repair state (status, detail, log path) beside its relay WARNING; release note 081.
- [ ] **Task 3.4**: `.venv-bootstrap.result` is written per view (keyed like the venv bootstrap logs), readers updated; release note 082.

## Success Criteria

- [x] Targeted tests for the provision relay step and the `--check` mode pass.
- [x] Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/078-provision-sh-provisions-the-relay-binary.md` records the release-bound consequence (holding-area artefact); the plan has no other release-bound consequence.
- [ ] Targeted QA (`llm_qa.py changed --base origin/main`) passes.

## Delivery & Milestones

- Provision relay step and `--check` mode: see the branch commits.
