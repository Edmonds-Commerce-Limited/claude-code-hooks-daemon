# Plan 00554: rust relay transport default

**Status**: In Progress
**Created**: 2026-10-27
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

Owner request: "in the next release, lets make the rust transport the default, with legacy left as an opt in (but please raise a ticket if you do need to revert)".

The relay was already the default in the example config and `init-config` (Plan 00529), but the model default in code stayed off, so a config with no `transport` block, or a partial one, ran the legacy bash and python3 forwarder. This plan makes the code default match: `relay_enabled` is true on hosts that can run the relay (Linux x86_64 and aarch64, else false) and `relay_source` is `auto` when the key is absent. An explicit `false` is respected, so `relay_enabled: false` is the legacy opt-in; an explicit `null` is invalid config (the field is a bool).

No blocker to flipping the default was found, so no revert ticket is raised. The fallback ladder stays intact: provisioning never aborts an install, `relay_binary_checker` warns and starts a repair, and the forwarder guard falls through to nc and then bash when the binary is unusable.

## Goals

- A config that omits `daemon.transport.relay_enabled` gets the relay.
- `relay_enabled: false` (or `bin/hooks-daemon transport off`) keeps the legacy transport.
- Docs, docstrings and the release note describe the relay as the default and the legacy transport as the opt-in.

## Non-Goals

- No release, tag or publish.
- No change to the relay binary, the protocol or the fallback ladder.

## Design decisions

- `load_transport_config`: a missing config file gives the defaults (relay on); an unusable or malformed config gives legacy, because the opt-out cannot be read.
- `transport_toggle` seeds `relay_enabled: true` when the key is absent.
- `relay_binary_checker` stays silent when there is no config file.

## Tasks

### Phase 1: Flip the default

- [x] ✅ **Task 1.1**: `TransportConfig` defaults, loader fallback, toggle seed, checker behaviour
- [x] ✅ **Task 1.2**: legacy-path unit and integration tests opt out explicitly
- [x] ✅ **Task 1.3**: docs and docstrings describe the relay as the default
- [x] ✅ **Task 1.4**: release note and config-changes manifest staged in UNRELEASED
- [ ] ⬜ **Task 1.5**: targeted QA green, merge to main (coordinator)

## Success Criteria

- [x] Unit directories install, config, daemon and handlers/session_start, plus the relay and transport integration files, pass.
- [x] Release-bound consequences are recorded in the holding area: `CLAUDE/UPGRADES/UNRELEASED/release-notes/009-rust-relay-transport-default.md` and `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.72.0.yaml`.
- [ ] Targeted QA over the branch passes.

## Delivery & Milestones

- `2b4a6bd0c`: model default, loader fallback, toggle seed, unit tests.
- Integration tests, docs, release note and manifest: the commits after it on `worktree-relay-default`.
