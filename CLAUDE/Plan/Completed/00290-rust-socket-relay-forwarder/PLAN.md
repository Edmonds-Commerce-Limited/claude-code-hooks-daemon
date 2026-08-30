# Plan 00290: rust socket relay forwarder

**Status**: Complete
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

- [x] ✅ **Task 2.1**: TDD the multi-socket listener: daemon binds one socket
  per registered hook event alongside the existing socket; event inferred
  from listener identity; existing protocol untouched on the legacy socket.
- [x] ✅ **Task 2.2**: Socket hygiene — stale per-event sockets cleaned like
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

- [x] ✅ **Task 4.1**: Reworked `.claude/hooks/*` generation —
  `install/forwarder_generator.py::generate_forwarder_content` inserts the
  pure-builtin relay guard block above `source init.sh` when
  `relay_enabled`, and appends the event's bash_key to the
  `send_request_stdin`/`forward_stop_event` call when `nc_enabled`; both
  transforms are independent, idempotent, and no-ops by default (pinned by a
  byte-identical test against every real deployed hook). Wired into
  `scripts/install/hooks_deploy.sh::deploy_all_hooks` as a post-`cp`
  regeneration step (skipped in self-install mode); the `nc -U` rung itself
  lives in `init.sh::send_request_stdin`, gated on
  `HOOKS_DAEMON_NC_UNIX_CAPABLE` + the generated socket-name arg, buffering
  payload/response via temp files (never shell variables) and replaying to
  the python3 rung on an empty capture.
- [x] ✅ **Task 4.2**: Fail-open preserved end-to-end — acceptance tests
  (`tests/integration/test_relay_guard_fail_open.py`) drive REAL generated
  forwarders against the actual built relay binary for daemon-down
  (connect-fail → exec fallback with stdin intact → reaches `ensure_daemon`)
  and binary-missing (guard's own `-x` test skips cleanly to the legacy
  path), plus nc-missing (broken `nc` degrades to python3, payload
  genuinely replayed) and `--no-relay` re-entry loop-safety (a forwarder
  invoked with `--no-relay` never re-attempts the relay even with a working
  binary and socket present).

### Phase 5: Distribution and release integration

**Owner ruling (2026-08-30)**: client projects get the OPTION of compiling the
relay themselves or downloading a precompiled binary from the GitHub release —
and the source ships either way (it is in this package regardless). This
system being open source is important, and shipping precompiled binaries is a
departure from that posture — so build-from-source is the first-class route
(preferred whenever a Rust toolchain is present), the precompiled download is
the convenience option, both are explicit choices recorded in config, and
neither ever happens implicitly (the relay rung is opt-in to begin with).

- [x] ✅ **Task 5.1**: Release pipeline builds the binaries and emits sha256
  manifests; a client that CHOOSES the download option fetches from the GitHub
  release and the installer verifies the digest before deploying the binary,
  falling back (with an advisory) on mismatch. No implicit downloads —
  `scripts/release/build_relay_release_assets.sh` +
  `install/relay_deploy.py::deploy_relay_from_download`.
- [x] ✅ **Task 5.2**: Build-from-source path — preferred when a Rust
  toolchain is present (plain `rustc`, no cargo/crates per the design);
  probe output records which route produced the deployed binary; the source
  file is shipped in the package either way —
  `install/relay_deploy.py::deploy_relay_from_build`/`check_musl_toolchain`,
  `transport_probe.py` `toolchain_present`/`deployed_route`, `hooks-daemon.env`
  threading via `scripts/install/transport_env.sh` (closes the Phase 4
  deferral).
- [x] ✅ **Task 5.3**: UPGRADES config-changes + truth-changes manifest
  entries; HANDLER_REFERENCE/architecture docs updated; opt-in clearly
  documented as experimental for this release — validated through the real
  `ConfigMigrationManifest`/`TruthChangeManifest` loaders.

### Phase 6: Measurement and QA gate

- [x] ✅ **Task 6.1**: Extended the Plan 00154 bench harness
  (`assets/bench_relay_forwarder.sh`); recorded p50/p95 for a typical
  PreToolUse event on all three rungs in
  [MEASUREMENT-relay.md](MEASUREMENT-relay.md). Relay p50 4.344 ms / p95
  5.056 ms — under the ≤6 ms criterion on both statistics. Fresh python3
  baseline on this container: 34.111 ms p50. The nc rung was initially found
  broken (hangs ~30 s per call — missing `-N` on `nc -U -w`, plus a
  `forwarder_generator.py::regenerate_deployed_hooks` gating bug); both
  fixed upstream same day (commit `4a8c2e50`) and re-measured: p50
  22.426 ms / p95 23.439 ms — functional, ~5x slower than relay.
- [x] ✅ **Task 6.2**: Dogfood soak live and QA gate green. The first flip
  surfaced two genuine bugs (relay guard `exec`ing past
  `forward_stop_event`'s exit-code-2 hard-block translation; baked socket
  path breaking daemon-isolation fixtures — journal has the full story),
  fixed at `c9a0f674` (Stop/SubagentStop excluded from the guard;
  `${HOOKS_DAEMON_EVENTS_DIR:-…}` overrides). Re-flip committed at
  `54422e79`: relay enabled in this repo, 29 forwarders carry the guard,
  stop/subagent-stop excluded. Verified against that exact state: stop
  hard-block acceptance 3/3 (manual `exit=2` check included), live relay
  round-trip, fail-open with daemon stopped, daemon RUNNING with 31
  per-event listeners. Full `llm_qa` gate green (tests 15835/15835; the
  four regression categories cleared at `aa6d2a5b`).

## Success Criteria

- [x] ✅ Relay path measured ≤6 ms p50 end-to-end for a typical PreToolUse
  event (4.344 ms p50, 5.056 ms p95); the relay's own connect-fail fallback
  and daemon-down fail-open were proved live in this repo before the
  dogfood flip was reverted (see Task 6.2) — both fallback mechanisms work
  correctly on their own terms, independent of the Stop-hook gap found.
- [x] ✅ Default config behaviour is byte-identical to today (opt-in OFF ⇒ no
  behaviour change for existing installs) — proven by generation tests and
  by this repo's forwarders staying diff-free until the deliberate flip.
- [x] ✅ Binary is std-only, static, digest-verified at install, and carries no
  policy; bash path remains complete and readable (570,056 bytes stripped,
  readelf-verified no ELF interpreter, sha256-gated deploy).
- [x] ✅ Full QA passes (final gate green against the live dogfood state);
  docs, config manifests updated. Release notes are the release's job
  (human-gated `/release`).

## Delivery & Milestones

- Design + per-event listeners + relay + forwarder integration:
  `47e80b0e` → `228e766b` → `4f988048` → `8cabdb04`.
- Distribution/release integration: `3cbbf87a`; measurement: `759d2521`,
  `9b33a568` (relay p50 4.344 ms; nc p50 22.426 ms; python3 baseline
  p50 34.111 ms).
- Dogfood-exposed bug fixes: `4a8c2e50` (nc -N + gating), `c9a0f674`
  (stop exclusion + env overrides); QA regression clear: `aa6d2a5b`.
- Dogfood soak live in this repo: `54422e79`.
