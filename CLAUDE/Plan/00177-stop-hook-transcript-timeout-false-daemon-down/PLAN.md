# Plan 00177: Stop hook false "daemon not running" on long sessions — client read-timeout on unbounded whole-file transcript parsing

**Status**: In Progress
**Created**: 2026-07-20
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (delicate Stop path; acceptance testing is main-thread only)

## Overview

On a long-running session the **Stop** hook begins returning, after ~30 s,
`{"decision":"block","reason":"Hooks daemon not running - protection not active"}`
while the daemon is demonstrably alive (stable PID, socket present, every other
event served). It is a false negative: nothing is down. The client socket has a
single hard-coded 30 s timeout covering the whole request/response, and on a
large transcript the built-in `auto_continue_stop` handler parses the **entire**
transcript from byte zero, repeatedly (up to ~9 whole-file parses per dispatch),
which blows the 30 s budget. The client raises `socket.timeout` and — because the
timeout path is not distinguished from a dead socket — emits the "daemon not
running" block, steering operators to needlessly restart a healthy daemon.

Verified against the upstream tree (v3.44.0). Two independent root causes compose
the failure; both are fixed here. (The downstream bug report cited an in-tree
reference implementation `backlog_stop_blocker.py` — that is a *downstream*
project handler and does NOT exist upstream, so the bounded tail-read is written
from scratch here.)

Source report: `untracked/hooks-daemon-handler-failure.md`.

## Goals

- **A (messaging):** a client `socket.timeout` (daemon was reached — connect+send
  succeeded) must surface as an honest "daemon is ALIVE, do NOT restart" outcome,
  never as "daemon not running". Genuine-down cases (`socket_not_found` /
  `connection_refused`) keep their truthful block.
- **B (efficiency):** the Stop hot path must read the transcript with a **bounded
  tail read** (seek near EOF, parse only the last N bytes), not a whole-file
  materialisation, so a Stop dispatch on a multi-hundred-MB transcript completes
  in milliseconds and never approaches the client budget.
- No regression in the delicate `auto_continue_stop` freshness / STOPPING-BECAUSE
  logic — the fix makes each read cheap, it does NOT change the routing logic.

## Non-Goals

- Per-dispatch transcript memoisation via a request-scoped context object
  (report §3). With bounded tail reads each parse is sub-10 ms, so ~9 tail reads
  is negligible; a shared-cache refactor is deferred (YAGNI) and captured as a
  follow-up.
- The ccy PTY supervisor lifetime injection-cap issue (report Appendix A) — a
  separate component (`.claude/ccy/claude-supervise.py`); captured as a follow-up,
  not fixed here.
- Changing the full-history `TranscriptReader.load()` or its non-Stop consumers
  (`data_layer`, `idle_housekeeping_advisor`, `nitpick`).

## Context & Background

Confirmed source facts:

- `init.sh` python forwarder (`emit_error_json`, lines 875-939): for
  Stop/SubagentStop every `error_type` except `invalid_hook_input` collapses to
  `reason = 'Hooks daemon not running - protection not active'` (line 926).
  `socket_timeout` (raised at 1021-1024 after a successful connect+sendall) lands
  there.
- `TranscriptReader._parse()` (transcript_reader.py:143-205) streams the whole
  file and materialises every entry; `get_last_assistant_message()` (494-503)
  reads the tail of a fully-materialised list.
- `get_transcript_reader()` (stop_hook_helpers.py:41-62) builds a **fresh**
  `TranscriptReader` per call — no cross-call reuse.
- `auto_continue_stop` parses the whole file in `matches()` (328), at `handle()`
  entry (359), Branch 3 reload (411), and up to 6 more times in
  `_await_fresh_assistant_message()` (657-659). The poll is self-amplifying: slow
  parses make the tail look "stale", triggering the poll.

Blast radius of `get_transcript_reader`: only the three Stop handlers
(`auto_continue_stop`, `hedging_language_detector`, `dismissive_language_detector`),
all of which need only the recent conversation tail. `.claude/init.sh` is deployed
byte-for-byte from the canonical `/workspace/init.sh` (`hooks_deploy.sh:186`).

## Tasks

### Phase 1: Client timeout messaging (Problem A) — `init.sh`

- [ ] ⬜ **Task 1.1**: Add an env-overridable socket timeout
  (`CLAUDE_HOOKS_SOCKET_TIMEOUT`, default 30) in the python forwarder so the
  timeout path is fast-testable and operators gain a lever.
- [ ] ⬜ **Task 1.2**: Give `socket_timeout` its own honest branch in
  `emit_error_json`: for Stop/SubagentStop, the daemon was reached, so emit an
  honest "ALIVE — do NOT restart; transcript likely very large; /compact restores
  fast Stops" outcome and **fail-open** (allow the stop) rather than a misleading
  fail-closed block that wedges + loops. Genuine-down (`socket_not_found` /
  `connection_refused`) stays fail-closed with the truthful message.
- [ ] ⬜ **Task 1.3**: Integration test driving a mock Unix socket server that
  accepts then stalls, with a short `CLAUDE_HOOKS_SOCKET_TIMEOUT`, asserting the
  honest reason + non-block for Stop, and that genuine-down still blocks.
- [ ] ⬜ **Task 1.4**: Redeploy `.claude/init.sh` from source; verify byte-identity.

### Phase 2: Bounded tail read (Problem B) — `transcript_reader.py`

- [ ] ⬜ **Task 2.1**: RED — tests for a new `load_tail(path, max_bytes)`:
  correctness of last-assistant/last-tool-use accessors over the tail; proves it
  does NOT depend on file head (garbage/huge head, valid tail); record-boundary
  realignment (drop partial first line); tiny-file and empty-file behaviour.
- [ ] ⬜ **Task 2.2**: GREEN — refactor `_parse` line-handling into a shared
  helper consumed by both `load()` (whole file) and `load_tail()` (seek to
  `max(0, size-N)`, drop partial first line, parse remainder). Named constant
  `_DEFAULT_TAIL_BYTES`. No change to `load()` semantics.
- [ ] ⬜ **Task 2.3**: REFACTOR + 95% coverage on new code.

### Phase 3: Wire tail read into the Stop hot path

- [ ] ⬜ **Task 3.1**: `get_transcript_reader()` uses `load_tail()`.
- [ ] ⬜ **Task 3.2**: `auto_continue_stop._await_fresh_assistant_message()` uses
  `load_tail()` per poll iteration.
- [ ] ⬜ **Task 3.3**: Regression — full existing Stop-handler suite green
  (auto_continue_stop, hedging, dismissive) proving logic unchanged.

### Phase 4: Integrate, QA, dogfood

- [ ] ⬜ **Task 4.1**: `./scripts/qa/run_all.sh` (or `llm_qa.py all`) — all pass.
- [ ] ⬜ **Task 4.2**: Daemon restart → RUNNING; live Stop probe on a large
  synthetic transcript returns fast + correct.
- [ ] ⬜ **Task 4.3**: Config/truth-changes manifests if warranted; docs; cleanup
  the source report from `untracked/`.

## Technical Decisions

### Decision 1: Fail-open (allow) on a read-side Stop timeout

**Context**: Today a `socket_timeout` on Stop emits `decision:block`, which wedges
the user's stop for 30 s and then re-fires → a repeating 30 s stall.
**Decision**: For a read-side timeout (daemon reached, handler slow) on
Stop/SubagentStop, degrade to fail-open with an honest diagnostic. Connect/send
failures (genuine down) remain fail-closed. Blocking a human because an advisory
handler was slow is strictly harmful, and a bounded tail read makes the timeout a
rare backstop anyway.
**Date**: 2026-07-20

### Decision 2: Bounded tail load as a new method, `load()` untouched

**Context**: `load()` has non-Stop consumers that may want full history.
**Decision**: Add `load_tail()` (new), switch only the Stop hot path to it. Lowest
blast radius; the delicate freshness *logic* is unchanged — only the reads get
cheap.
**Date**: 2026-07-20

## Success Criteria

- [ ] A live Stop probe against a large synthetic transcript returns in well under
  the client budget with correct routing.
- [ ] A simulated slow/hung daemon yields an honest "ALIVE — do not restart"
  outcome (not "daemon not running"); a genuinely absent socket still blocks.
- [ ] All existing Stop-handler tests pass unchanged; new tests cover tail read +
  timeout messaging.
- [ ] Full QA passes; daemon restarts RUNNING.

## Delivery & Milestones

<!-- commit hashes recorded as work lands -->

## Notes & Updates

- Failsafe recovery cron: `6f4f8ab4` (hourly at :37, non-durable).
- Follow-ups captured (out of scope here): per-dispatch memoisation (report §3);
  ccy supervisor lifetime injection-cap reset (report Appendix A).
