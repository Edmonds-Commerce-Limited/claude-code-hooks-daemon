# Plan 00125: Auto-detect containers → uv copy mode (silence hardlink warning on upgrades)

**Status**: Complete
**Created**: 2026-06-13
**Owner**: Claude (Opus)
**Priority**: Medium (papercut hotfix)
**Type**: Bug Fix / Enhancement
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded

## Overview

Every daemon install/upgrade inside a container prints the scary
`⚠ uv hardlink failed (likely overlay-fs) — retrying with UV_LINK_MODE=copy`
warning, wastes a first `uv sync` attempt, then retries with copy mode.

`create_venv_at_path` (`scripts/install/venv.sh`) already detects
hardlink-hostile filesystems proactively — but only by probing the **target**
filesystem type (`overlay*`/`nfs*`). In a typical container the project (and
its `untracked/` dir) is **bind-mounted from the host**, so the venv target
sits on the host fs (ext4/xfs/btrfs) while uv's cache lives on the container's
overlay fs. The two are **cross-device**, so `uv` hardlink fails even though
the target fs is not overlay/nfs — the proactive probe misses it and the
warn-then-retry fallback fires on every container upgrade.

## Goal

Auto-detect a container environment and choose `UV_LINK_MODE=copy` up front
(same as the existing overlay/nfs branch), so container installs do a single
clean copy-mode sync — no failed attempt, no warning.

## Non-Goals

- No change to the explicit-`UV_LINK_MODE` escape hatch (operator value always wins).
- No change to normal-disk hardlink-first behaviour.
- No change to the overlay/nfs fs-type probe (kept; container check is additive).

## Approach

Add a `_uv_in_container` bash helper to `venv.sh` using portable signals:

- the `container` env var (`podman`/`docker`/`oci`/`crio` — Podman/systemd set it),
- Podman's `/run/.containerenv`,
- Docker's `/.dockerenv`.

Marker paths are overridable via `HOOKS_DAEMON_CONTAINERENV_PATH` /
`HOOKS_DAEMON_DOCKERENV_PATH` so the negative test case can run from inside a
real container (the CI/dev container has `/run/.containerenv`). Wire it into the
`first_link_mode` decision: if no explicit `UV_LINK_MODE`, fs-probe did not
already pick copy, AND we are in a container → copy, with an informational line.

## Tasks

### Phase 1: RED

- [x] Failing test: container marker + non-overlay fs → copy mode up front, no warning
- [x] Negative test: no container (markers overridden absent) + normal fs → hardlink-first
- [x] Escape-hatch test: explicit UV_LINK_MODE respected even in a container

### Phase 2: GREEN

- [x] Add `_uv_in_container` helper to `scripts/install/venv.sh`
- [x] Wire container check into the `first_link_mode` decision

### Phase 3: Verify

- [x] Targeted bash/venv tests green
- [x] Full QA `./scripts/qa/llm_qa.py all`
- [x] Daemon restart RUNNING

## Success Criteria

- [x] Container install/upgrade emits no `uv hardlink failed` warning
- [x] Explicit UV_LINK_MODE and normal-disk behaviour unchanged
- [x] All QA passes

## Notes & Updates

### 2026-06-13

- Follow-up to v3.19.1; reported by user: "upgrades in container always complain about uv can't hardlink".
- Root cause: existing proactive probe checks target fs type only; container bind-mount makes cache↔target cross-device, which the type probe cannot see.
