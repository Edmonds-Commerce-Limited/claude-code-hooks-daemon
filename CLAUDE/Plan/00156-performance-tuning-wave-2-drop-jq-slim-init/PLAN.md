# Plan 00156: Performance Tuning Wave 2 — drop jq, slim init.sh

**Status**: In Progress
**Created**: 2026-07-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**Themes**: performance

## Overview

Wave 2 of the performance programme (see `CLAUDE/Performance/README.md`). Wave 1
(Plan 00155) landed the pure daemon-side wins T1 + T4. Wave 2 tackles the two
biggest remaining costs, both in the **bash forwarder** — the safety-critical
per-event transport measured in Plan 00154:

- **T2 — drop `jq`**: every hook wrapper spawns `jq -c '{event, hook_input: .}'`
  once (~22-24 ms p50) to wrap stdin; status-line spawns it twice (wrap +
  response unwrap). The wrapper *already* spawns a `python3 -c` transport
  process; moving the wrap/unwrap into that same Python removes the `jq` spawn
  entirely at ~microsecond cost. Expected ~−22 ms on every latency-path event.
- **T3 — slim `init.sh`**: `source init.sh` costs ~13.2 ms p50 before any daemon
  traffic. Replace `tr` pipelines with bash parameter expansion, skip
  `mkdir -p` when the dir exists, short-circuit avoidable subshells. Est. −5-8 ms.

This is the highest-blast-radius surface in the system: EVERY hook event flows
through it. The prime directive holds — **no loss of functionality or
stability**. The JSON-never-through-shell-variables invariant (payload passes via
stdin, never argv) is preserved; only the hardcoded event-name literal moves to
argv. `test_dogfooding_hook_scripts.py` keeps the deployed `.claude/hooks/*`
copies byte-identical to `install.py` output, so source-of-truth and deployed
copies cannot drift.

## Goals

- Eliminate `jq` from all hook forwarder wrappers (8 standard + stop/subagent-stop
  - status-line), moving JSON wrap/unwrap into the existing `python3` transport.
- Slim the `init.sh` hot path (parameter expansion over `tr`, conditional
  `mkdir`, fewer subshells) without regressing any guarded edge case.
- Keep the fail-open / fail-closed error contract byte-for-byte: Stop/SubagentStop
  emit `decision=block`; other events emit fail-open `hookSpecificOutput`.
- Keep the source of truth (`init.sh`, `install.py`) and deployed `.claude/`
  copies in sync (dogfooding test green).
- Full QA green, daemon RUNNING after every change, forwarder acceptance gates pass.

## Non-Goals

- No change to daemon-side dispatch, handler logic, or any handler decision.
- No compiled/Rust transport (Rule 2: only after free wins land and budget still
  fails — this IS the free win).
- No change to the socket protocol or the daemon's request/response schema.
- T5/T6 (content-scanner passes, orjson) are out of scope — deferred/not-recommended.

## Tasks

### Phase 1: T2 — drop jq from the transport

- [x] ✅ **Task 1.1**: RED — extend transport tests to assert `send_request_stdin`
  wraps raw stdin `hook_input` into `{event, hook_input}` given an event-name arg,
  injects `hook_event_name` for Status, and preserves control chars.
- [x] ✅ **Task 1.2**: GREEN — rewrite `send_request_stdin` in `init.sh` to take an
  event-name argv, parse stdin, build the request in Python, and (Status mode)
  extract `.text`/`.error` with the existing fallback text.
- [x] ✅ **Task 1.3**: Update `forward_stop_event` to stop calling `jq` (pass the
  event name to `send_request_stdin`).
- [x] ✅ **Task 1.4**: Update `install.py` `create_forwarder_script` +
  `create_status_line_script` templates to the jq-free form.
- [x] ✅ **Task 1.5**: Regenerate deployed `.claude/hooks/*` (`.claude/init.sh` is a
  symlink to the edited root `init.sh`); `test_dogfooding_hook_scripts.py` green.
- [x] ✅ **Task 1.6**: Full QA 13/13; restart daemon (RUNNING); forwarder acceptance
  gates (`test_stop_hook_hard_block.py`, dogfooding, CI-passthrough) green;
  live-probed pre-tool-use (allow + deny) and status-line against the real daemon.

### Phase 2: T3 — slim init.sh hot path

- [ ] ⬜ **Task 2.1**: Profile `source init.sh` with `bash -x`+timestamps to
  attribute the 13.2 ms and record a before number.
- [ ] ⬜ **Task 2.2**: RED/GREEN per shortcut — `tr`→`${var,,}`/`${var// /-}` in
  `_get_hostname_suffix`, `[[ -d ]] || mkdir -p`, subshell short-circuits — each
  guarded by its scenario test.
- [ ] ⬜ **Task 2.3**: Sync `install.py` + deployed copies; dogfooding test green.
- [ ] ⬜ **Task 2.4**: Full QA; daemon RUNNING; re-profile for an after number; commit.

### Phase 3: Close-out

- [ ] ⬜ **Task 3.1**: Update `CLAUDE/Performance/README.md` backlog (T2/T3 → Landed)
  - measured-results table; update `BASELINE.md` if re-measured.
- [ ] ⬜ **Task 3.2**: Plan completion checklist (status→Complete, git mv to
  Completed/, README row + stats, single atomic commit).

## Success Criteria

- [ ] No `jq` invocation remains in any deployed `.claude/hooks/*` wrapper or in
  `send_request_stdin`/`forward_stop_event` (jq may remain only in
  `emit_hook_error`'s pure-error path).
- [ ] Every event's request/response and error contract is behaviourally
  identical (verified by acceptance gates + live probes).
- [ ] `test_dogfooding_hook_scripts.py` green (deployed == installer output).
- [ ] Full QA green (13/13), coverage ≥95%, daemon RUNNING.
- [ ] Measured before/after recorded in the Performance hub.

## Notes & Updates

### 2026-07-12

- Plan scaffolded for Wave 2 (T2 + T3) on branch `feature/performance-tuning`.
- Failsafe recovery cron `219a8c62` created (non-durable, hourly at :37).
- Source-of-truth map confirmed: `init.sh` (root; `.claude/init.sh` is a SYMLINK
  to it, so one edit updates both); `install.py` `create_forwarder_script`
  (line ~234) + `create_status_line_script` (line ~316) generate the wrappers;
  deployed copies held in sync by `tests/integration/test_dogfooding_hook_scripts.py`.
- **T2 landed (Phase 1)**: all three `send_request_stdin` definitions + the eight
  standard wrappers + status-line + `forward_stop_event` are jq-free. Wrapping and
  status `.text`/`.error` extraction moved into the existing `python3` transport;
  event name passes via argv (a hardcoded literal), payload stays on stdin. New
  guard suite `tests/integration/test_forwarder_jq_free.py` (33 tests) drives the
  real wrappers with a broken-`jq` shim on PATH. Full QA 13/13, 9814 tests,
  coverage 95.6%. Committed on branch `feature/performance-tuning`.
