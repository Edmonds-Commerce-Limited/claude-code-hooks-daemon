# Plan 00542: statusline fast path raw text

**Status**: In Progress
**Created**: 2026-10-21
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #131

## Overview

The status line is the highest-frequency hook: Claude Code calls it as often as once a second per session. Each call
of the generated forwarder (`.claude/hooks/status-line`, from `install/forwarder_generator.py`):

- sources `init.sh` (3780 lines);
- forks about 11 helpers;
- starts a fresh `python3`, found through PATH, to talk to the daemon socket.

Measured at about 0.081 s wall and 0.077 CPU-s per call, which is about 7.7% of a core per session at a 1 s refresh.
A pyenv shim on PATH makes the interpreter start several times dearer.

The same request sent straight to the per-event status socket costs about 0.007 s and 0.002 CPU-s, through
`nc -U -N` or the existing Rust relay (`relay/hooks_relay.rs`, Plan 00290). Neither can be used today for two reasons:

- the reply is JSON, and extracting `.text` needs a decoder;
- the Python rung forwards the terminal size.

Evidence: the triage report, [RESEARCH-COST.md](RESEARCH-COST.md).

Fix: let a status request ask the daemon for raw text and carry the terminal size in the request. A byte pump then
prints the reply as-is, and the forwarder gains a fast path ahead of `source init.sh` that falls through to today's
path on any failure.

## Goals

- When the daemon is up, a status tick costs about a tenth of today's CPU, with no `init.sh` and no interpreter start.
- The daemon-down behaviour is unchanged: `DAEMON FAILED`, venv building and version mismatch (Plan 00488, #72).
- Terminal-size-aware rendering (Plan 00167) still works on the fast path.

## Non-Goals

- A new Go or Rust client. The existing std-only relay is the compiled client.
- Turning the relay on by default, or changing how its binary is distributed. Both are Plan 00529's owner decision.
- Changing `refreshInterval`.

## Tasks

### Phase 1: Raw status text and a forwarder fast path (TDD)

- [ ] ⬜ **Task 1.1**: The daemon answers a status request with raw text when the request asks for it, taking the
  terminal size from the request. An ordinary status request is answered as before, so the Python rung keeps working.

- [ ] ⬜ **Task 1.2**: The generated status-line forwarder gains a fast path ahead of `source init.sh`, built from
  bash builtins only:

  - it builds the raw request;
  - it sends it through the relay binary when that is executable, else `nc -U -N` when the host's nc is capable;
  - it uses a short timeout and prints the reply.

  It falls through to the existing path on no socket, a refused connection, a timeout, an empty reply or an error
  reply.

- [ ] ⬜ **Task 1.3**: Measure the generated forwarder before and after on this host (daemon up, 6 runs). Record the
  numbers here.

### Phase 2: Relay found missing although enabled

- [ ] ⬜ **Task 2.1**: This repo's config has `relay_enabled: true`, but `untracked/bin/hooks-relay` is absent, so
  every forwarder's relay guard silently falls through to bash. Recorded as N523 in the Plan 00474 niggles ledger for its own fix. A
  missing binary that the config claims is enabled should be surfaced, not swallowed.

## Success Criteria

- [ ] With the daemon up, a status tick is answered by the fast path, and its measured CPU per call drops by at least 5x.
- [ ] With the daemon down, the status line shows the same text as before. Tests cover each fall-through case.
- [ ] Release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- Triage: issue #131 comment; evidence in [RESEARCH-COST.md](RESEARCH-COST.md).
