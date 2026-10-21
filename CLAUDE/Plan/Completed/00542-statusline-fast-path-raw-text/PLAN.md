# Plan 00542: statusline fast path raw text

**Status**: Complete
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
- Turning the relay on by default for every hook, and how its binary is distributed. The owner has decided both, and the
  work is Plan 00529 Task 2. This plan makes the status line use the relay.
- Changing `refreshInterval`.

## Owner rulings that reshape Phase 1

Plan 00529 records them:

- the relay is the default, starting with the status line;
- performance is a priority, because many sessions now run at once;
- **no silent fallbacks: loud and clear, fail fast.**

So a failure the fast path can name is shown loudly on the status line, naming the fix: a configured relay that is
missing, a daemon too old for raw text, a timeout, or an error reply. It does not fall through quietly to the Python
rung. The one hand-off that stays is a daemon that is not running at all. That goes to the existing start-up path,
which starts the daemon and shows `DAEMON FAILED` or venv building loudly (Plan 00488, #72). That is recovery, not a
silent substitute.

## Tasks

### Phase 1: Raw status text and a forwarder fast path (TDD)

- [x] ✅ **Task 1.1**: The daemon answers a status request with raw text when the request asks for it, taking the
  terminal size from the request. An ordinary status request is answered as before, so the Python rung keeps working.

- [x] ✅ **Task 1.2**: The generated status-line forwarder gains a fast path ahead of `source init.sh`, built from
  bash builtins only:

  - it builds the raw request;
  - it sends it through the relay binary when that is executable, else `nc -U -N` when the host's nc is capable;
  - it uses a short timeout and prints the reply.

  As first built, it fell through silently on any failure. Task 1.4 makes those failures loud.

- [x] ✅ **Task 1.4**: Loud failures (owner ruling).

  - A configured relay that is missing or not executable prints a red status naming the fix.
  - A reply without the raw-text marker prints a red "daemon too old for raw status, restart" status.
  - A timeout or an error reply prints a red status naming what failed.
  - Only "no daemon running" (no socket, or the connection refused) hands off to the start-up path, which reports
    loudly.

  Each case is tested.

- [x] ✅ **Task 1.3**: Measure the generated forwarder before and after on this host (daemon up). Record the
  numbers here.

  - Before: 0.077 CPU-s per tick (bash, `init.sh`, a fresh python3; [RESEARCH-COST.md](RESEARCH-COST.md)).
  - After, through the relay, with the forwarder at its absolute path as Claude Code runs it: 20 ticks took 0.116 CPU-s
    (user 0.053 + sys 0.063) and 0.254 s wall, so about 0.006 CPU-s and 13 ms per tick. About 13x less CPU.

### Phase 2: Relay found missing although enabled

- [x] ✅ **Task 2.1**: This repo's config has `relay_enabled: true`, but `untracked/bin/hooks-relay` was absent, so
  every relay-eligible forwarder's guard fell through to bash. Only the transport toggle or verify step reported it.

  - The status line now prints a red line naming `bin/hooks-daemon transport on` when the binary is missing (Task 1.4).
  - `transport on` provisioned it here by building it, but printed "nothing to do" (N525).
  - Surfacing a missing binary for the other forwarders is N523, owned by Plan 00529 Task 2.

## Success Criteria

- [x] With the daemon up, a status tick is answered by the fast path, and its measured CPU per call drops by at least 5x.
- [x] With the daemon down, the status line shows the same text as before (the no-socket and refused cases hand off to
  the unchanged start-up path; pinned in `tests/unit/install/test_forwarder_status_fast_path.py`).
- [x] No fast-path failure is silent. Every case shows a loud status naming the fix, and is tested.
- [x] Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/008-status-line-fast-path-raw-text.md` (the
  pending-release holding area).

## Delivery & Milestones

- Triage: issue #131 comment; evidence in [RESEARCH-COST.md](RESEARCH-COST.md).
- Delivered: b476a3911 (raw text and fast path), 8d882fdc2 (sentinel), 864f3f99d (loud failures); merged to main as
  901e59a7a.
