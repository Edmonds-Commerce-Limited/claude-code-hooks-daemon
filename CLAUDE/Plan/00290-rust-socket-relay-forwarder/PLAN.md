# Plan 00290: rust socket relay forwarder

**Status**: In Progress
**Created**: 2026-08-30
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00154 measured a full hook event at ~45 ms end-to-end, of which the daemon
(socket + dispatch across ~38 handlers) accounts for ~1.8 ms. The other ~43 ms
is the client-side forwarder stack spawned for every event: fresh `bash`
(~2 ms), sourcing `init.sh` (~13 ms), and the `python3 -c` transport spawn
(measured 13.5 ms median on this machine; `jq` was already removed by
Plan 00156). RUST-TRADEOFFS.md Option C named the one compiled increment that
pays for itself: a tiny static transport-only binary.

This plan implements Option C with a refinement that makes the binary dumber
than originally specced: **per-event Unix sockets**. The daemon listens on one
socket per hook event (e.g. `pre-tool-use.sock`), so the event name is encoded
in *which file* the relay connects to and the relay does no JSON wrapping at
all — stdin → socket, socket → stdout, timeout, exit code. The Rust relay is
std-only (zero crates; `std::os::unix::net`), built as a fully static
`*-unknown-linux-musl` binary in the few-hundred-KB range.

**Owner rulings (2026-08-30, recorded verbatim in intent)**: the Rust forwarder
ships **opt-in for this release** (config default OFF); the design is
**config-driven** with a **fallback ladder** — relay binary → `nc -U` (where a
Unix-capable netcat exists) → the current bash+python3 transport — so the fat
bash path's guarantees (`ensure_daemon` auto-start, fail-open JSON error
emission) are never lost. Shipping any compiled artifact to client repos is a
posture change for an auditability-first project; the owner has signed off on
the opt-in basis, with sha256 manifests and an optional build-from-source path
as the mitigations.

## Goals

- Hook event end-to-end cost drops from ~45 ms to ≤6 ms on the relay path
  (measured, not estimated — extend the Plan 00154 bench harness).
- Daemon listens on per-event Unix sockets alongside the existing single
  socket (which remains the compatibility path).
- A std-only static Rust relay binary (~300 LOC target) with timeout,
  exit-code translation, and exec-fallback to the bash forwarder on any
  failure to connect.
- Config block governs the whole transport choice; default preserves today's
  behaviour exactly. Opt-in flag enables the relay hot path.
- Bash forwarders gain the middle rung: try `nc -U` before the python3
  transport when the config enables it and the probed `nc` supports `-U`.
- Distribution: prebuilt binaries with sha256 manifests in the release
  pipeline, plus build-from-source when a Rust toolchain is present; installer
  probes and records which transport rungs are available.

## Non-Goals

- No policy in the binary — every block/allow decision stays in readable
  Python. The relay is transport only.
- No Rust rewrite of daemon internals (Options A/B were rejected by the
  Plan 00154 evidence; that verdict stands).
- No change to the wire protocol's response semantics — handlers, front
  controller and JSON verdict shapes are untouched.
- No removal of the bash+python3 path — it is the permanent fallback and the
  default for this release.
- No TCP loopback listener (`/dev/tcp` pure-bash rung): rejected — it trades
  Unix-socket file permissions for port/token management. Record in design doc.
- Claude Code natively consuming sockets (no exec at all) is out of scope —
  the ~2-3 ms spawn of the hook command itself is the accepted floor; a
  possible upstream feature request, not this plan.

## Tasks

### Phase 1: Design

- [x] ✅ **Task 1.1**: Write `DESIGN-socket-relay.md` in this folder: per-event
  socket naming/location, lifecycle, event↔socket mapping, framing, timeout
  and exit-code contract, and the full fallback ladder — delivered as
  [DESIGN-socket-relay.md](DESIGN-socket-relay.md) §1–§3, §5.
- [x] ✅ **Task 1.2**: Specify the config schema (`daemon.transport`: relay
  enabled default false, nc rung flag, timeout, binary path override) and the
  installer probe recording rung availability —
  [DESIGN-socket-relay.md](DESIGN-socket-relay.md) §4, §6.

### Phase 2: Daemon per-event listeners

- [ ] ⬜ **Task 2.1**: TDD the multi-socket listener: daemon binds one socket
  per registered hook event alongside the existing socket; event inferred
  from listener identity; existing protocol untouched on the legacy socket.
- [ ] ⬜ **Task 2.2**: Socket hygiene — stale per-event sockets cleaned like
  the existing socket; status/health output names the active listeners.

### Phase 3: Rust relay

- [x] ✅ **Task 3.1**: Implement the relay (std-only, no crates): argv names
  the socket path, stdin streamed to socket, response streamed to stdout,
  configurable timeout, distinct exit codes for connect-fail vs timeout vs
  protocol error; on connect-fail exec the bash forwarder (path via argv) —
  delivered as `relay/hooks_relay.rs`.
- [x] ✅ **Task 3.2**: Rust unit/integration tests plus a daemon-side
  acceptance test driving a real event through the relay end-to-end —
  stub-server harness `relay/test_relay.py` (9 cases, all passing); the
  daemon-side end-to-end acceptance run is Phase 6's gate (Task 6.2).
- [x] ✅ **Task 3.3**: Static build (`x86_64`/`aarch64-unknown-linux-musl`),
  stripped size recorded; build script committed; CI job added —
  `relay/build.sh` (x86_64 built: 570,056 bytes stripped; aarch64 awaits a
  builder, per design §3.2); CI job specified in design §3.2, wired Phase 5.

### Phase 4: Bash forwarder integration

- [ ] ⬜ **Task 4.1**: Rework `.claude/hooks/*` generation: when the config
  enables the relay and the binary is present, the hook command execs the
  relay directly (no `init.sh` on the hot path); otherwise the existing
  script shape, with the `nc -U` rung inserted before the python3 transport
  when enabled and probed available.
- [ ] ⬜ **Task 4.2**: Preserve fail-open: every rung's failure lands in the
  next rung; the last rung keeps `ensure_daemon` + JSON error emission.
  Acceptance tests for daemon-down, binary-missing, and nc-missing paths.

### Phase 5: Distribution and release integration

**Owner ruling (2026-08-30)**: client projects get the OPTION of compiling the
relay themselves or downloading a precompiled binary from the GitHub release —
and the source ships either way (it is in this package regardless). This
system being open source is important, and shipping precompiled binaries is a
departure from that posture — so build-from-source is the first-class route
(preferred whenever a Rust toolchain is present), the precompiled download is
the convenience option, both are explicit choices recorded in config, and
neither ever happens implicitly (the relay rung is opt-in to begin with).

- [ ] ⬜ **Task 5.1**: Release pipeline builds the binaries and emits sha256
  manifests; a client that CHOOSES the download option fetches from the GitHub
  release and the installer verifies the digest before deploying the binary,
  falling back (with an advisory) on mismatch. No implicit downloads.
- [ ] ⬜ **Task 5.2**: Build-from-source path — preferred when a Rust
  toolchain is present (plain `rustc`, no cargo/crates per the design);
  probe output records which route produced the deployed binary; the source
  file is shipped in the package either way.
- [ ] ⬜ **Task 5.3**: UPGRADES config-changes + truth-changes manifest
  entries; HANDLER_REFERENCE/architecture docs updated; opt-in clearly
  documented as experimental for this release.

### Phase 6: Measurement and QA gate

- [ ] ⬜ **Task 6.1**: Extend the Plan 00154 bench harness; record before/after
  p50/p95 for a typical PreToolUse event on all three rungs in
  `MEASUREMENT-relay.md`.
- [ ] ⬜ **Task 6.2**: Full QA green; daemon restart verified; dogfood the
  relay in this repo (opt-in flipped ON here only) for a soak period before
  release notes claim the numbers.

## Success Criteria

- [ ] Relay path measured ≤6 ms p50 end-to-end for a typical PreToolUse event;
  fallback rungs each verified working by acceptance test.
- [ ] Default config behaviour is byte-identical to today (opt-in OFF ⇒ no
  behaviour change for existing installs).
- [ ] Binary is std-only, static, digest-verified at install, and carries no
  policy; bash path remains complete and readable.
- [ ] Full QA passes; docs, config manifests and release notes updated.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
