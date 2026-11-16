# Plan 00609: tracked hook wrappers machine independent

**Status**: Not Started
**Created**: 2026-11-16
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The generated relay hot-path block in the `.claude/hooks/*` wrappers
(`install/forwarder_generator.py`) embeds values that differ per machine or
per checkout: the absolute checkout path (the `BASH_SOURCE` prefix test, the
untracked directory, the relay binary path, `HOOKS_DAEMON_RELAY_DAEMON_ROOT`)
and, per a peer report, a runtime directory and an events-dir hash. Verified
in this repository: `.claude/hooks/pre-tool-use` lines 19-41 carry the literal
checkout path. A project that tracks its wrappers gets a dirty checkout on
every other machine or view that regenerates them, and the converge step
skips it. Reported by a peer (no authority) from a client project tracking its
wrappers; the peer's tracked wrappers do not carry the block yet, so the next
upgrade will hit it.

The fix belongs in the daemon: tracked wrappers must be byte-identical across
machines and roots, so every machine-specific value is resolved at run time
(from `BASH_SOURCE`, `$PWD` or the existing project-root resolution), never
written into the file.

## Goals

- Regenerating the wrappers in two different roots yields byte-identical files.
- The relay hot path behaves as before: same socket, same binary, same fallback.
- Which values are machine-specific is established by measurement first, not
  assumed (the peer named a runtime directory and events-dir hash that this
  checkout's block does not show).

## Non-Goals

- Changing the relay protocol or the hostname-suffixed events directory layout.
- Untracking the wrappers.

## Tasks

### Phase 1: Defence and measurement

- [ ] ⬜ **Task 1.1**: Regenerate all wrappers in two different temp roots and
  list every byte that differs; record which are paths, uid, hash or host.
- [ ] ⬜ **Task 1.2**: Failing test: generation in two roots asserts identical
  bytes (this is the Defence; it also guards any later generated block).

### Phase 2: Fix

- [ ] ⬜ **Task 2.1**: Resolve each differing value at run time in
  `forwarder_generator.py`; keep the hot-path latency (no extra process spawns).
- [ ] ⬜ **Task 2.2**: Confirm the relay still engages (socket test, existing
  relay tests) and the fallback path is unchanged.
- [ ] ⬜ **Task 2.3**: Converge/upgrade: a wrapper with the old embedded block
  is rewritten once to the portable form; a second regeneration is a no-op.

### Phase 3: Release bound

- [ ] ⬜ **Task 3.1**: Release note under `CLAUDE/UPGRADES` pending area;
  holding-area artefact cited here before completion.

## Success Criteria

- [ ] Two-root regeneration test passes and fails on the old generator.
- [ ] No embedded absolute path, uid or hash in any generated wrapper.
- [ ] Relay hot path tests and full QA green in CI.
- [ ] Release-bound consequences recorded in the pending release notes.

## Delivery & Milestones

- Filed from a peer report; delivery commits are recorded here when merged.
