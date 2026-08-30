# MEASUREMENT — relay/nc/python3 rungs (Plan 00290, Task 6.1)

Reproduces the Plan 00154 method
([BENCHMARK-METHODOLOGY.md](../Completed/00154-daemon-performance-rust-vs-python-research/BENCHMARK-METHODOLOGY.md))
against the deployed `.claude/hooks/pre-tool-use` forwarder, once per rung.
Harness: [assets/bench_relay_forwarder.sh](assets/bench_relay_forwarder.sh).
Raw per-iteration microseconds and the computed summary are in
[assets/results/](assets/results/) (`python3.us`, `nc.us`, `relay.us`,
`summary.json`).

## Environment

Linux 7.1.8-200.fc44.x86_64 container, 22 CPUs, self-install mode, daemon
source at commit `3cbbf87a`, package version `3.56.0`, Python 3.11.2, Rust
`rustc 1.98.0`. Different container from Plan 00154's recorded run (that was
`7.0.13-200.fc44.x86_64`) — absolute numbers are not directly comparable to
00154's, which is exactly why this task re-measures the python3 baseline
fresh rather than reusing 00154's ~45 ms figure.

## Method

For each rung: configure `daemon.transport` in `.claude/hooks-daemon.yaml`,
restart the daemon (binds/unbinds the per-event listeners), regenerate the
deployed forwarders for that config, then run
`bench_relay_forwarder.sh <rung> assets/results 60` — 3 warmups (discarded)

- 60 recorded iterations of `bash .claude/hooks/pre-tool-use` fed a fixed
  PreToolUse `Bash` payload (`ls -la /workspace`) on stdin, timed wall-clock
  with `date +%s%N` exactly as Plan 00154's `bench_forwarder.sh`. Percentiles
  are nearest-rank over raw samples. Sequential single client, one rung
  running at a time.

The scenario is the plan's "typical PreToolUse Bash event" — the same
payload shape 00154 used for its `wrapper_pre_tool_use` scenario.

## Results

| Rung                          | n   | p50 (ms)   | p95 (ms)   | mean (ms)  | min (ms)   | max (ms)   |
| ----------------------------- | --- | ---------- | ---------- | ---------- | ---------- | ---------- |
| (c) python3 (today's default) | 60  | 34.111     | 39.289     | 34.672     | 30.390     | 40.500     |
| (a) relay → per-event socket  | 60  | **4.344**  | **5.056**  | 4.372      | 3.877      | 5.338      |
| (b) bash + `nc -U`            | 6\* | 30,071.572 | 30,074.796 | 30,067.343 | 30,051.804 | 30,074.796 |

\*Rung (b)'s run was truncated at 6 iterations — see "nc rung: broken, not
just slow" below; the numbers are real recorded latencies, not a partial
artifact of stopping early.

**Success criterion — relay ≤6 ms p50**: **MET.** Relay p50 is 4.344 ms
(27.6% headroom under the 6 ms bar) and p95 is 5.056 ms, also under 6 ms.
Both the p50 and the p95 numbers sit inside the target, so the bar is met on
both statistics, not just on p50.

**Baseline comparison**: this container's freshly-measured python3 baseline
(34.111 ms p50) is lower than Plan 00154's recorded ~45 ms — expected, given
the different container/date noted above; both were measured with the same
method against the same production forwarder shape. Relative to *this run's
own* baseline, the relay rung is a **7.86×** reduction in p50 (34.111 ms →
4.344 ms) and removes essentially the entire client-side forwarder stack
(bash startup + `init.sh` sourcing + python3 transport spawn) that Plan
00154's component breakdown identified as the cost.

## nc rung: broken, not just slow

The bash-`nc -U` rung (b) does **not** save time — it adds roughly 30
seconds to every single hook event on this container, then still falls
through to the python3 rung for the actual answer. Six iterations were
recorded (all ~30.05–30.07 s) before the harness's own timeout truncated the
run; a 7th `nc` process was still hung and had to be killed manually.

**Root cause** (diagnosed, not fixed — out of this task's scope per the
assigning instructions): `init.sh`'s `send_request_stdin` invokes
`nc -U -w "${CLAUDE_HOOKS_SOCKET_TIMEOUT:-30}" "$_nc_sock" < "$_nc_payload" > "$_nc_response"`.
The per-event socket protocol ([DESIGN-socket-relay.md](DESIGN-socket-relay.md)
§2) is EOF-framed: the daemon reads until the client half-closes
(`shutdown(SHUT_WR)`), then writes its response. OpenBSD `nc` (the variant on
this container: `OpenBSD netcat (Debian patchlevel 1.219-1)`) does **not**
shut down the socket's write half on stdin EOF unless told to — that needs
its `-N` flag ("shutdown the network socket after EOF on the input"), which
the invocation does not pass. Without it, `nc` keeps the connection open
after its stdin file hits EOF, the daemon never sees EOF on its read side,
so it never sends a response, and `nc` sits until the `-w` timeout elapses —
consistently ~30 s, matching `-w`'s default. The subsequent
"empty/short capture → replay to python3" fallback ([DESIGN-socket-relay.md](DESIGN-socket-relay.md)
§5) does correctly kick in afterward and deliver a valid verdict — fail-open
integrity holds — but only after paying the full 30 s tax. Verified directly:
running `bash .claude/hooks/pre-tool-use` under this config `time`s at ~30 s
wall, and `ps` during a hung call shows a live `nc -U -w 30 …/pre-tool-use.sock`
process that only exits at the timeout.

This is a defect in `.claude/init.sh`'s `send_request_stdin` (a daemon-owned
deployed asset, not project config) and in
`regenerate_deployed_hooks` in `install/forwarder_generator.py`, which was
also found broken independently while wiring this measurement: it early-returns
`[]` whenever `transport.relay_enabled` is `False`, **even when
`nc_enabled` is `True`** — so the nc-only rung's forwarder-side transform
(`append_nc_socket_arg`) is never applied through the production
CLI/install path at all, though the underlying `generate_forwarder_content`
function does implement it correctly when called directly. Both are
daemon/installer source; per this task's scope constraints ("do not modify
relay/daemon/installer source... STOP, report it") these were **not**
patched. To measure the nc rung's forwarder-side change at all, the
`generate_forwarder_content` function was called directly (bypassing the
broken `regenerate_deployed_hooks` gate) for that one measurement window,
then reverted. **Reported to the coordinator; both issues need upstream
fixes before `nc_enabled` is usable in any repo.**

**Consequence for this repo's dogfood config (Task 6.2)**: `nc_enabled`
stays `false`. Given the finding above, this is not merely "measurement
didn't show a benefit" — it is actively unsafe to enable until the two bugs
above are fixed. The relay rung is unaffected by either defect (its guard
block and socket contract are independent of `nc`/`send_request_stdin`).

## Rung availability recap

`bin/hooks-daemon transport-probe --project-root /workspace` after the
relay deploy:

```
Relay binary present                 : True
Relay binary executable              : True
Relay binary digest                  : unknown (no manifest)
Relay binary deployed via            : build
Build toolchain present (musl rustc) : True
nc on PATH                           : True
nc Unix-socket capable (-U)          : True
Per-event socket dir present         : True
```

`nc Unix-socket capable (-U)` being `True` reflects only that the binary
*advertises* `-U` support (probed from `nc -h` usage text per design §6.3),
not that the current `send_request_stdin` invocation actually works with it
— the defect above is orthogonal to that probe.
