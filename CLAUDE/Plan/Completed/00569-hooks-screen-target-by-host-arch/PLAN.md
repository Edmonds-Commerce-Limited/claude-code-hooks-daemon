# Plan 00569: hooks screen target by host arch

**Status**: Complete
**Created**: 2026-11-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #174

## Overview

The deployed ccy supervisor (`.claude/ccy/claude-supervise.py`) finds the
`hooks-screen` binary through `resolve_screen_binary`. Its last candidate, the
`screen/build.sh` output, is named by a constant pinned to
`x86_64-unknown-linux-musl`, and nothing in the supervisor reads the CPU
architecture. On an aarch64 host it therefore looks for an x86_64 build. A
client whose QA rejects artefacts pinned to one architecture can only exclude
the deployed file, because every upgrade overwrites a local edit.

The build script already accepts a `SCREEN_TARGET` triple, but its default is
pinned to x86_64 as well. When no binary resolves, the screen check notes only
"no hooks-screen binary found", naming neither the architecture nor the triple
it searched for.

## Goals

- The supervisor derives the hooks-screen target triple from the host machine
  architecture: x86_64/amd64 and aarch64/arm64, both on musl.
- An unsupported architecture skips the build-output candidate, and the
  failure note names the architecture. Fail-open is unchanged.
- `screen/build.sh` defaults `SCREEN_TARGET` from the host architecture with
  the same mapping, and refuses an unknown architecture with a clear message.

## Non-Goals

- Changing the relay's architecture handling, or any CI workflow.
- Building or shipping an aarch64 hooks-screen artefact in CI or releases.
- Changing the candidate order (override, deployed path, build output).

## Tasks

### Phase 1: Host-architecture target selection

- [x] ✅ **Task 1.1**: Failing tests: machine-to-triple mapping for both
  architectures, their aliases and an unknown one; the resolver on aarch64
  finds the aarch64 build and not the x86_64 one; the unsupported case; the
  failure note's content.
- [x] ✅ **Task 1.2**: Implement the mapping in the supervisor (stdlib only,
  injectable machine value) and use it in `resolve_screen_binary` and the
  failure note.
- [x] ✅ **Task 1.3**: `screen/build.sh` takes its default target from
  `uname -m`; update the screen docs that state the x86_64-only default.
- [x] ✅ **Task 1.4**: Targeted QA, merge, and a release note.

## Success Criteria

- [x] Tests that failed before the fix cover both architectures and pass after it.
- [x] No architecture-pinned triple remains as the supervisor's only screen
  target.
- [x] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` records the
  user-visible change, the pending-release holding area for this plan's
  release-bound consequence: a client can drop any exclude of the deployed
  supervisor added for this defect.
- [x] Issue #174 is commented and closed after a verified merge and green CI.

## Delivery & Milestones

- Fix merged at `ae0af5761`; main CI green (run 42404687976, on `4b1317734`).
  Release note 003 is in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`. #174
  commented and closed.
