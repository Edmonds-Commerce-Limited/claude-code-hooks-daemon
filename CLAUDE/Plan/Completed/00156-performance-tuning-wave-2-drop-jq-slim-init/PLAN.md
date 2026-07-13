# Plan 00156: Performance Tuning Wave 2 — drop jq, slim init.sh

**Status**: Complete
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

- [x] ✅ **Task 2.1**: Profiled `source init.sh` — ~12.46 ms avg over 50 runs
  (incl. ~2 ms bash startup), consistent with Plan 00154's 13.2 ms p50.
- [x] ✅ **Task 2.2**: Applied the two portable, bash-3.2-safe spawn removals,
  each behaviour-locked by characterization tests
  (`tests/integration/test_init_hot_path.py`): `_get_hostname_suffix` drops one
  `tr` spawn + the `echo` pipeline via `${var// /-}` (lowercase stays on `tr`
  for macOS bash 3.2 — no `${var,,}`); the unconditional `mkdir -p` is guarded
  with `[[ -d ]] ||`. Deliberately DEFERRED the risky ones (delicate
  cross-platform `stat`/`date` in `_exec_bit_selfheal`; the `dirname` walk whose
  `${var%/*}` top-level edge case differs) — marginal gain, real stability risk.
- [x] ✅ **Task 2.3**: init.sh only (wrappers unchanged); `.claude/init.sh` is a
  symlink to the edited root `init.sh`, so the deployed copy updates atomically.
  Dogfooding test green.
- [x] ✅ **Task 2.4**: Full QA; daemon RUNNING; re-profiled ~11.07 ms avg
  (≈1.4 ms/event saved by removing 2 process spawns). Committed.

### Phase 3: Close-out

- [x] ✅ **Task 3.1**: Updated `CLAUDE/Performance/README.md` backlog (T2/T3 →
  Landed, plan 00156), Wave 2 measured-results table, and Waves section.
  `BASELINE.md` kept as the Plan 00154 canonical baseline; Wave 2 deltas live in
  the hub's measured-results table.
- [x] ✅ **Task 3.2**: Plan completion checklist — status→Complete, git mv to
  Completed/, README row + stats, single atomic commit.

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
- **T3 landed (Phase 2)**: `init.sh` source dropped ~12.46 → ~11.07 ms avg
  (~1.4 ms/event) by guarding `mkdir -p` and removing one `tr` spawn from
  `_get_hostname_suffix`. Characterization tests
  `tests/integration/test_init_hot_path.py` lock the behaviour. Full QA 13/13,
  9822 tests, coverage 95.6%.
- **Delivery commits** (branch `feature/performance-tuning`): scaffold `83f5f91`,
  T2 `b88d424`, T3 `c4fff5b`, close-out `8c45d42`, measured-hub `24331e1`. Wave 2
  net: ~−22 ms on every latency-path event (jq removed) + ~−1.4 ms/event (init.sh
  slim), with handler decisions, the request envelope, the Stop exit-2 contract,
  and the status-line/error responses all behaviourally unchanged.

### 2026-07-13 — Independent review + fixes

- **Fable code review** (`code-reviewer` agent, Fable model) run over the Wave 2
  diff; captured verbatim in `REVIEW-fable-wave2.md`. Verdict **APPROVE WITH
  NITS**, 7 findings (5 MINOR, 2 NIT), none blocking. Transport rewrite confirmed
  correct on payload fidelity, Stop contract, injection surface, and bash-3.2
  portability.
- **Fixes applied** (TDD, QA 13/13, daemon restart RUNNING):
  - F1 — `invalid_hook_input` now gets a payload-specific advisory that does NOT
    tell the agent to restart the daemon (the daemon is fine; the payload was bad).
  - F2 — both CI-passthrough `send_request_stdin` overrides render `⚠️ NO STATUS DATA` in status mode instead of leaking a raw JSON blob to the status line.
  - F3 — the status-mode `fail()` branch re-emits the `HOOKS DAEMON ERROR` stderr
    diagnostic (no silent error suppression).
  - F4 — new `test_untracked_dir_created_when_absent` exercises the mkdir-when-
    absent branch of the T3 guard in a sandbox project (the old test only ever hit
    dir-exists).
  - F5 — new tests pin the one changed behaviour: malformed payload → non-Stop
    fails open (exit 0, advisory), Stop fails closed (exit 2).
  - F6 — the tautological `test_precondition_jq_is_installed` is now an honest
    skip marker.
  - F7 — stale `jq`-referencing comments in `init.sh` corrected; dead `env.pop`
    line removed.
  - Documentation: the "byte-identical" claim in `CLAUDE/Performance/README.md` is
    corrected to note the single intentional malformed-payload divergence.
  - Out of scope (per review): the pre-existing unescaped `$error_details`
    interpolation in `emit_hook_error`'s jq-less fallback (`init.sh` ~line 142) —
    flagged as a follow-up ticket, not a Wave 2 regression.
