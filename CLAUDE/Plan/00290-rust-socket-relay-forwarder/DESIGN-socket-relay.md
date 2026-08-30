# DESIGN — Per-event sockets + Rust relay forwarder (Plan 00290, Tasks 1.1/1.2)

Grounded in the code as of commit `1a0bb7f7`. File references are to real
modules read while designing; the schema section names exact keys.

## 0. What this changes, in one paragraph

The daemon gains **one additional Unix listener per wired hook event**
alongside the existing single socket (which keeps its protocol untouched,
forever). A **static Rust relay binary** becomes the opt-in hot path for the
`.claude/hooks/*` forwarders: stdin → per-event socket → stdout, no JSON
handling at all, because *which socket* it connected to already names the
event. Every failure that the relay cannot serve lands in the existing bash
forwarder, which retains `ensure_daemon` and fail-open JSON error emission
unchanged. Default config keeps today's behaviour byte-identical.

## 1. Per-event sockets

### 1.1 Location and naming

The legacy socket is `{untracked}/daemon{suffix}.sock` where `{untracked}` is
`daemon/paths.py::_get_untracked_dir()` (self-install: `{project}/untracked/`;
client: `{project}/.claude/hooks-daemon/untracked/`) and `{suffix}` is
`_get_hostname_suffix()` (`-{lowercased, space→dash hostname}`; resolution
order `$HOSTNAME` → OS hostname → `localhost`, memoised).

Per-event sockets live in a **sibling directory**, one file per event:

```
{untracked}/events{suffix}/{event-file-name}.sock
# e.g. untracked/events-cc4247671d91/pre-tool-use.sock
```

- `{event-file-name}` is the kebab-case forwarder name — identical to the
  `.claude/hooks/` filename for that event (`pre-tool-use`, `status-line`,
  `user-prompt-submit`, …). The 1:1 forwarder↔socket naming is the point of
  the design: no mapping table exists anywhere at runtime.
- The set of sockets is exactly `constants/events.py::wired_event_metas()` —
  catalogued-but-unwired events (Plan 00170 burn-down) get no socket, the same
  rule that gates forwarders and settings entries today.
- New `daemon/paths.py` helpers, DRY with the existing ones:
  `get_event_socket_dir(project_dir)` and
  `get_event_socket_path(project_dir, event_file_name)`. Both reuse
  `_get_untracked_dir` + `_get_hostname_suffix` and apply the same
  `_UNIX_SOCKET_PATH_LIMIT` fallback as `get_socket_path` (the per-event dir
  falls back alongside the legacy socket, or per-event listeners are skipped
  with a WARNING log when even the fallback exceeds the limit — the legacy
  path is then the only transport, which is always safe).

### 1.2 Permissions and lifecycle

- Directory `0o750`, sockets `0o660` — matching the legacy socket's chmod in
  `HooksDaemon.start`.
- **Bind**: after the legacy socket is bound (inside the existing
  `_acquire_socket_and_bind` flock critical section, so concurrent starts
  serialise once for all sockets). Per-event binding is best-effort: a failure
  to bind one event socket logs ERROR and continues — the legacy socket
  carries that event via the bash rung.
- **Unlink**: in `HooksDaemon.shutdown`, alongside the legacy socket unlink.
- **Stale cleanup**: the whole `events{suffix}/` dir participates in the
  existing stale-file cleanup (`stale_file_days`, `touch_daemon_files_in_dir`
  already touches the parent untracked dir; the events dir is added to the
  periodic touch). On start, a pre-existing `events{suffix}/` dir is removed
  wholesale before binding — per-event sockets carry no reuse semantics; the
  liveness-probe/reuse protocol (Plan 00127) remains the legacy socket's job,
  and a start that loses the reuse race (`DaemonAlreadyRunningError`) never
  touches the events dir (the incumbent owns it).

### 1.3 Gating

Per-event listeners are bound **iff the config enables any rung that needs
them** (`daemon.transport.relay_enabled or daemon.transport.nc_enabled` —
§4). With both false (the default) the daemon binds only the legacy socket
and nothing about today's runtime changes.

## 2. Wire framing on per-event sockets

The legacy socket keeps its exact protocol: one newline-delimited JSON request
`{"request_id"?, "event", "hook_input"}` → one newline-terminated JSON
response (`server.py::_handle_client` / `_process_request`). Untouched.

Per-event sockets use **EOF-delimited framing** instead:

1. Client connects, streams the raw hook payload (exactly the bytes Claude
   Code wrote to the forwarder's stdin), then half-closes the write side
   (`shutdown(SHUT_WR)`).
2. The daemon reads to EOF (bounded by
   `constants/protocol.py::SocketLimit.REQUEST_BUFFER_BYTES`, the same cap the
   legacy readline uses), parses the bytes as JSON, and dispatches through the
   **same** `_process_request` path by synthesising the legacy envelope
   internally: `{"event": <from socket identity>, "hook_input": <parsed>}`.
   The event name comes from which listener the connection arrived on — the
   `_handle_client` callback is bound per-listener via `functools.partial`.
3. The daemon writes the response JSON and closes. No trailing-newline
   requirement in either direction.

Why EOF framing: the raw payload is arbitrary JSON produced by Claude Code —
newline-delimited framing would make the relay responsible for asserting
"exactly one line", which is protocol knowledge the relay must not have. EOF
framing lets the relay be a pure byte pump. `_system` requests, request_id
correlation and the input-validation/strict-mode logic are unchanged — they
ride `_process_request` exactly as before (per-event requests simply never
carry a `request_id`; the forwarders never set one today either).

## 3. The Rust relay

### 3.1 Contract

Single source file `relay/hooks_relay.rs` (repo root `relay/` directory),
**std only — zero crates, no Cargo.lock, no dependency tree**. Built with
plain `rustc` (no cargo needed for a crate-less single file):

```
rustc --edition 2021 -O -C strip=symbols \
  --target x86_64-unknown-linux-musl relay/hooks_relay.rs -o hooks-relay
```

Measured floor on this container (Rust 1.98.0): a static musl std binary is
~450 KB stripped and spawns in ~1 ms. Target size ceiling: 1 MB.

Argv:

```
hooks-relay <socket-path> [--fallback <script-path>] [--timeout-ms <n>]
```

Behaviour, in order:

1. `connect(<socket-path>)` **before reading any stdin**. On ANY connect
   failure (ENOENT, ECONNREFUSED, EACCES, timeout): stdin is still intact, so
   if `--fallback` was given, `execv("/bin/bash", [<script-path>, "--no-relay"])` — the bash forwarder inherits stdin/stdout untouched and
   the process image is replaced (no extra process lingers). Without
   `--fallback`: exit 10, nothing written to stdout (diagnostic mode).
2. Pump stdin → socket (64 KiB buffer loop), then `shutdown(SHUT_WR)`.
3. Pump socket → stdout until EOF, honouring `--timeout-ms` (default 30000,
   matching the python3 transport's `CLAUDE_HOOKS_SOCKET_TIMEOUT` default)
   across the whole exchange via `SO_RCVTIMEO`/`SO_SNDTIMEO`.
4. Exit codes: `0` response delivered; after the first stdin byte has been
   consumed a fallback exec is no longer possible, so mid-exchange failures
   emit the **fail-open empty response `{}`** to stdout and exit `0` (Claude
   Code must always receive valid JSON — this mirrors
   `emit_hook_error`'s fail-open contract and carries no policy: `{}` is
   "no opinion", the same thing a passthrough emits today). The distinct
   codes `11` (timeout) and `12` (I/O or oversized-response error) are used
   ONLY in `--no-fallback` diagnostic invocations where a harness wants to
   see the failure class instead of the fail-open JSON.
5. A short stderr line (`hooks-relay: <class>: <detail>`) accompanies every
   non-0-path so daemon logs/debug capture can attribute transport failures.

Explicit non-behaviours (this is what keeps the transparency cost low): the
relay never parses JSON, never reads config, never starts the daemon, never
retries, never writes files, and contains no event names.

### 3.2 Distribution

- Release assets: `hooks-relay-x86_64-unknown-linux-musl` (aarch64 added when
  a builder exists) + `SHA256SUMS` covering them, produced by a CI job.
- In-repo: `relay/hooks_relay.rs` (the auditable source) and
  `relay/SHA256SUMS.released` (digests of the shipped binaries, updated by
  the release pipeline).
- Install/upgrade: the installer deploys the binary to
  `{untracked}/bin/hooks-relay` ONLY when `relay_enabled: true`, verifying
  the digest first; on mismatch it refuses the binary, logs an advisory, and
  the ladder simply runs without rung 1. Where no prebuilt matches the
  platform and `rustc` is present, build-from-source is offered (same
  one-line `rustc` invocation); the probe records which route provided the
  binary.
- The binary lives under `untracked/` (never committed to a client repo), so
  a client repo's auditable surface remains 100% source.

## 4. Config schema

New `TransportConfig` model in `config/models.py`, `extra="forbid"` (the
Plan 00288 `LayoutConfig` conventions), attached to the existing
`DaemonConfig` — transport is daemon infrastructure, so it lives under the
`daemon:` block rather than at top level:

```yaml
daemon:
  transport:
    relay_enabled: false   # rung 1: exec the static relay binary (opt-in)
    nc_enabled: false      # rung 2: bash nc -U path (opt-in)
    timeout_seconds: 30    # relay --timeout-ms source; also nc -w budget
    relay_binary: null     # absolute-path override; null = {untracked}/bin/hooks-relay
```

- Defaults produce **byte-identical behaviour to today**: no per-event
  listeners, no relay deploy, forwarders unchanged.
- `timeout_seconds` intentionally mirrors the python3 transport's 30 s
  default; `CLAUDE_HOOKS_SOCKET_TIMEOUT` keeps overriding the python3 rung
  and is honoured by the generated relay guard too (env wins over config at
  the call site, same precedence the transport has today).
- Validated through the real loader; an unknown key inside `transport:` is a
  hard config error (`extra="forbid"`).
- `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.57.0.yaml` gains the block
  (options-added, default-off) in Phase 5.

## 5. Fallback ladder

Rung order at event time: **relay → bash(ensure_daemon → nc → python3)**.

| Rung                     | Reached when                                                                       | Failure                                                             | Lands in                                                                               |
| ------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| 1 relay                  | config `relay_enabled` AND binary executable AND event socket file exists          | connect-fail (daemon down, socket stale, perms)                     | exec rung 2/3 script with stdin intact (`--fallback`)                                  |
| 1 relay                  | (as above)                                                                         | timeout / IO error / oversized response AFTER stdin consumed        | fail-open `{}` to stdout, exit 0 (cannot fall back; stdin is spent)                    |
| 2 nc                     | inside bash forwarder, after `ensure_daemon`; `nc_enabled` AND probed `-U`-capable | empty/short output, non-zero exit, timeout                          | rung 3 in the same bash process (response captured, not streamed, so retry is safe)    |
| 3 python3 (today's path) | always the last rung                                                               | daemon down after start attempts, socket timeout, malformed payload | `emit_hook_error` fail-open JSON — unchanged behaviour, still owns ALL error messaging |

Ownership rules the table encodes:

- **`ensure_daemon` never moves.** Only the bash rung starts the daemon. The
  relay's connect-fail exec therefore lands every daemon-down event in
  exactly today's code path, cold-start behaviour included.
- **Fail-open JSON is owned by bash** (`emit_hook_error`) in every case
  where bash is still reachable; the relay emits it only in the one state
  where bash cannot be re-entered (stdin consumed mid-exchange).
- Rung 2 buffers the response (`response=$(... | nc ...)` is NOT the shape —
  the payload goes via a temp-file-free redirect with the response captured
  from the socket by `nc`; if the capture is empty the payload is REPLAYED to
  rung 3, which is safe because the daemon treats each connection
  independently and an empty capture means no verdict was delivered).

## 6. Forwarder integration and the probe

### 6.1 Forwarder shape

`settings.json` registrations are untouched (still
`bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<event>`) — no
`hook_registration_checker` churn, no re-registration on upgrade. The change
is inside the deployed forwarder scripts (which are daemon-owned client
assets: `install/client_owned_assets.py` maps `.claude/hooks/*` 1:1), by
inserting a **generated relay guard** ABOVE the `source init.sh` line:

```bash
# --- relay hot path (generated; Plan 00290) ---
if [[ "${1:-}" != "--no-relay" ]]; then
    _rl_dir="<generated: untracked dir>"          # literal, install-mode aware
    _rl_sfx="-${HOSTNAME:-localhost}"; _rl_sfx="${_rl_sfx,,}"; _rl_sfx="${_rl_sfx// /-}"
    _rl_bin="<generated: relay binary path>"
    _rl_sock="$_rl_dir/events$_rl_sfx/pre-tool-use.sock"
    if [[ -x "$_rl_bin" && -S "$_rl_sock" ]]; then
        exec "$_rl_bin" "$_rl_sock" --fallback "${BASH_SOURCE[0]}" \
            --timeout-ms "<generated: timeout_seconds*1000>"
    fi
fi
# --- end relay hot path ---
source "$SCRIPT_DIR/../init.sh"   # existing body, unchanged
```

- Pure bash builtins — zero subshells, zero external spawns; the guard costs
  microseconds when the relay is disabled (files absent → straight through).
- The suffix expansion reproduces `_get_hostname_suffix` semantics
  (lowercase, spaces→dashes) using bash's own `HOSTNAME` variable, which bash
  itself sets from `gethostname()` — the same OS value `paths.py` falls back
  to. This EXTENDS the existing init.sh↔paths.py hostname-agreement contract
  (init.sh line ~349); the acceptance suite asserts the three computations
  agree.
- `--no-relay` is how the relay's fallback exec re-enters the same script
  without recursing into rung 1.
- The guard block is **generated at deploy time** by the installer from the
  loaded config: when `relay_enabled: false` the guard is omitted entirely
  and the deployed file is byte-identical to today's. Config changes
  therefore take effect on `install`/`upgrade`/`deploy` (the same cadence as
  every other client-owned asset refresh), not on daemon restart — the
  restart-only surface is the per-event listeners.

### 6.2 nc rung placement

Inside `send_request_stdin` (init.sh): when the generated env file records
`HOOKS_DAEMON_NC_UNIX_CAPABLE=1` AND config `nc_enabled` was true at deploy
(also recorded there), attempt
`nc -U -w <timeout> "$_event_sock"` with the payload on stdin and capture the
response; empty capture falls through to the python3 block unchanged. This
saves the ~13.5 ms python3 spawn (measured) while keeping every error path in
bash. Detail deferred to Phase 4 implementation; the design constraint is
that rung 2 must REPLAY, never stream, so rung 3 always has the full payload.

### 6.3 Probe

`bin/hooks-daemon transport-probe` (new CLI verb, also run by the installer):

- relay binary present? executable? digest matches `SHA256SUMS.released`?
- `nc` on PATH and `-U`-capable (`nc -h` advertises `-U`)?
- per-event socket dir present (daemon running with listeners)?

Output: human-readable table + `--json`; the installer persists the two
deploy-time facts the bash side needs (`HOOKS_DAEMON_NC_UNIX_CAPABLE`,
effective rung enablement) into `hooks-daemon.env`, which init.sh already
sources.

## 7. Non-goals (binding, restated from PLAN.md)

- No policy in the binary — every allow/deny decision stays in Python.
- No Rust rewrite of daemon internals (Plan 00154 Options A/B stay rejected).
- No wire-protocol change on the legacy socket; the bash+python3 rung is
  permanent, not deprecated.
- No TCP/`/dev/tcp` rung: it trades Unix-socket file permissions for
  port+token management; rejected.
- Claude Code spawning no process at all (native socket hooks) is upstream's
  ground, not this plan's; the ~2-3 ms hook-command spawn is the accepted
  floor.

## 8. Measurement contract (Phase 6 inputs)

Baseline (Plan 00154 + this session): 45 ms end-to-end typical PreToolUse;
python3 transport spawn 13.5 ms median; `nc` spawn 0.7 ms; `bash -c true`
0.9 ms; daemon-side dispatch 1.8 ms p50. Targets: relay rung ≤6 ms p50
end-to-end; nc rung ≤ (45 − ~10) ms; disabled-config delta = 0 (asserted by
byte-comparing a deployed forwarder against the pre-00290 template).
