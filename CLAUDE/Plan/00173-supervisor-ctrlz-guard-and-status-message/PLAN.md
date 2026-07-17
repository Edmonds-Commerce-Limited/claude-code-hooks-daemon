# Plan 00173: Supervisor Ctrl+Z Guard and Status-Line Message Channel

**Status**: In Progress
**Created**: 2026-07-17
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Ctrl+Z is universal muscle memory for "undo", but a terminal interprets it as
SIGTSTP (suspend). Pressing it against Claude Code can suspend the session and
drop the user to a shell — hard to recover from, especially inside a container
where `fg`/job control is unfamiliar (upstream anthropics/claude-code#43596,
closed as not-planned). The ccy PTY supervisor already sits between the real
terminal and Claude's PTY and forwards stdin byte-for-byte, so it is the
natural place to neutralise this footgun.

This plan delivers THREE things:

1. **Supervisor input guard** — strip the `0x1a` (SUSP / Ctrl+Z) byte from the
   forwarded stdin stream so it can never reach Claude's PTY or suspend
   anything. Ctrl+Z becomes an inert, ignored keystroke.
2. **Supervisor → status-line transient message channel** — a **general,
   reusable** mechanism (the Ctrl+Z guard is merely its FIRST consumer): the
   supervisor writes a small JSON message file with a TTL; a new `status_line`
   handler reads it and renders the text, auto-omitting the segment once
   expired. Future supervisor events (compact fired, worker restart,
   arm/disarm, …) can post through the same channel.
3. **Thread safety as a first-class, documented concern** across ALL supervisor
   and status-line code — not just this feature. The message file is only the
   trigger: these components are inherently concurrent (see Concurrency Model
   below), and that reality must be made explicit in entry-point file headers
   and architecture docs so every future change respects it.

The message-channel design mirrors the existing `supervisor_indicator` status
handler in reverse: that handler READS a file the supervisor writes
(`supervise/supervisor-status.json`) and fails silent when it is absent. The
new channel is the same pattern applied to a `supervise/status-message.json`,
using the supervisor's already-proven atomic-write helper
(`write_supervisor_status`, `claude-supervise.py:933`).

## Concurrency Model (why thread safety is first-class here)

These files/dirs under `daemon_untracked_dir()/supervise/` (and the status
sidecars) are touched by MULTIPLE independent processes/threads at once:

- **Supervisor host process** — the main select loop forwarding I/O.
- **Supervisor `--worker` subprocess** — the decision worker, a separate PID
  also carrying the `claude-supervise` cmdline.
- **The daemon** — a DIFFERENT process that runs the status-line handlers and
  READS supervisor-written files on every render.
- **Multiple Claude Code sessions** — several sessions can share ONE daemon
  (Plan 00127) and each drives its own status renders; handlers with shared
  on-disk state (`thread_registry`, `context_sidecar`) see concurrent writers.

Consequences that every writer/reader in this area MUST honour:

- **Writes are atomic-replace only.** Write to a private temp file, then
  `os.replace()` (atomic rename on POSIX) — never write in place, so a reader
  never observes a half-written file. Temp names include BOTH pid and thread id
  (`.{name}.{pid}.{tid}.tmp`) so concurrent writers never clobber one another's
  temp file. Semantics are last-writer-wins (newest message overwrites).
- **Reads are fail-silent and defensive.** Missing / malformed / partial /
  foreign-schema files yield "no result", never an exception — a bad file must
  never break the status line or wedge the supervisor.
- **In-process shared mutable state is lock-guarded.** Any caches or counters
  touched from more than one thread (e.g. a writer's rate-limit state) use a
  `threading.Lock`.

## Goals

- Ctrl+Z (`0x1a`) pressed under the supervisor never reaches Claude and never
  suspends the session; it is silently dropped from the forwarded input stream.
- A reusable, TTL-bounded, **atomically-written** message file and a new
  status-line reader handler that fails silent when absent/expired/malformed.
- The Ctrl+Z guard uses the message channel to surface a brief, self-expiring
  "Ctrl+Z ignored" notice (rate-limited).
- Thread safety is documented as a first-class concern: header comments on the
  supervisor and status-line entry points, plus an architecture-doc section.
- Full TDD: supervisor unit tests (`tests/unit/supervise/`) and status handler
  unit tests; 95%+ coverage; QA green; daemon restart verified; supervisor
  version kept in lockstep with `version.py`.

## Non-Goals

- Fixing the direct-run (non-supervised) case — that is upstream Claude Code's
  to fix; the supervisor can only guard sessions it wraps.
- Remapping Ctrl+Z to an actual "undo" action (the issue's option 2). We only
  neutralise it; Claude's TUI owns undo semantics.
- Instantaneous on-keypress display. The status line only re-renders on Status
  events (≈ per turn / periodic), so the message appears/clears on render ticks,
  not the instant the key is pressed. Injecting into the PTY output stream for
  instant feedback is rejected — it corrupts the TUI frame.
- A bidirectional/queued message bus. One current-message file with a TTL is
  sufficient (YAGNI); newer messages overwrite older ones.
- A ground-up rewrite of existing concurrency handling. Phase 0 documents and
  audits; it only fixes a genuine race if the audit surfaces one.

## Context & Background

Key code paths (source of truth is the monolithic tracked
`.claude/ccy/claude-supervise.py`; tests load it via
`tests/unit/supervise/_load.py`; it is pure dogfooding with no `src/` copy):

- `_forward_io` (`claude-supervise.py:2192`) — the select loop. stdin is read
  at line ~2256 and written to `master_fd` at ~2259. The outer terminal is put
  in raw mode (`tty.setraw`, ~2379) so `ISIG` is OFF: Ctrl+Z is already NOT
  interpreted as a signal at the outer level — it arrives as a `0x1a` byte. The
  guard drops that byte before the `os.write(master_fd, ...)`.
- `InputActivity.record` (`claude-supervise.py:388`) — already parses
  fine-grained control bytes (Ctrl+U, Ctrl+C, backspace, bracketed paste,
  escape sequences); a `0x1a` filter fits this existing model.
- `write_supervisor_status` (`claude-supervise.py:933`) — the proven
  atomic-write helper: per-pid temp file `.{name}.{pid}.tmp` + `.replace()`.
  The new message writer reuses this, adding thread id to the temp name.
- `supervisor_indicator.py` — the mirror read pattern under
  `ProjectContext.daemon_untracked_dir()/supervise/`, fully fail-silent.

## Tasks

### Phase 0: Thread safety as a first-class concern (docs + audit)

- [ ] ⬜ **Task 0.1**: Audit the supervisor and every `status_line` handler for
  shared on-disk/in-memory state accessed by concurrent processes/threads;
  record findings (safe vs. needs-fix) in this plan. Fix any GENUINE race
  found; otherwise document why current handling is already safe.
- [ ] ⬜ **Task 0.2**: Add a concise "Thread Safety" header comment to the
  supervisor entry point (`.claude/ccy/claude-supervise.py`) and to the
  `status_line` package (`handlers/status_line/CLAUDE.md` + a short module note),
  stating the Concurrency Model rules above (atomic-replace, fail-silent reads,
  lock-guarded shared state).
- [ ] ⬜ **Task 0.3**: Add a "Thread Safety / Concurrency" section to the
  status-line architecture doc (`CLAUDE/Architecture/StatusLine.md`) and a
  supervisor equivalent, as the single source of truth future changes cite.

### Phase 1: Supervisor input guard (drop Ctrl+Z)

- [ ] ⬜ **Task 1.1**: RED — add `tests/unit/supervise/test_input_ctrlz_guard.py`
  asserting a stdin chunk containing `0x1a` has that byte removed before it
  reaches `master_fd` (surrounding bytes survive; multiple/embedded `0x1a`; a
  chunk that is only `0x1a`).
- [ ] ⬜ **Task 1.2**: GREEN — add a pure `strip_suspend(data: bytes) -> bytes`
  helper (named constant `_SUSPEND_BYTE = 0x1a`) and apply it in `_forward_io`
  between the stdin read and the `master_fd` write; feed the stripped bytes
  onward; keep `activity.record` semantics sane.
- [ ] ⬜ **Task 1.3**: Verify no regression to the input-line-guard model
  (`test_input_line_guard.py` still green) — Ctrl+Z is neither content nor a
  submit.

### Phase 2: Message channel (supervisor writer — thread-safe)

- [ ] ⬜ **Task 2.1**: RED — tests for a `StatusMessage` writer: writes
  `supervise/status-message.json` as `{"text": str, "expires_at": <epoch>}`
  atomically (temp `.{name}.{pid}.{tid}.tmp` + replace); overwrites prior
  message; tolerates unwritable dir (fail-safe, returns None); concurrent
  writers never corrupt the file (last-writer-wins).
- [ ] ⬜ **Task 2.2**: GREEN — implement the writer with named TTL constant and
  a `threading.Lock` around rate-limit state; wire the Ctrl+Z guard to post
  "Ctrl+Z ignored — use /exit to leave" (rate-limited so a key-mash does not
  thrash the file).

### Phase 3: Message channel (status-line reader handler)

- [ ] ⬜ **Task 3.1**: RED — `tests/unit/handlers/status_line/test_status_message.py`:
  renders text when present + unexpired; renders nothing when absent, expired,
  or malformed; never raises (fail-silent like `supervisor_indicator`).
- [ ] ⬜ **Task 3.2**: GREEN — new `status_line/status_message.py` handler (new
  `HandlerID` / `Priority` constants, `get_default_enabled=True` safe because
  absent-file ⇒ no segment). Register in config + docs.
- [ ] ⬜ **Task 3.3**: Shared path/schema constants documented as "MUST match
  the supervisor" (same convention `supervisor_indicator.py` uses).

### Phase 4: Integration, QA, dogfooding

- [ ] ⬜ **Task 4.1**: `generate-docs` to refresh `.claude/HOOKS-DAEMON.md`.
- [ ] ⬜ **Task 4.2**: `./scripts/qa/run_all.sh` (or `llm_qa.py all`) green.
- [ ] ⬜ **Task 4.3**: Daemon restart verified RUNNING; supervisor version
  lockstep test green
  (`test_compaction_gap_repro.py::TestSupervisorVersionMatchesDaemon`).
- [ ] ⬜ **Task 4.4**: Live dogfood — press Ctrl+Z in this supervised session,
  confirm no suspend and the message appears on the next status render.

## Technical Decisions

### Decision 1: Atomic-replace with pid+tid temp names (thread/process safe)

**Context**: The message file is written by concurrent processes (host, worker)
and potentially multiple threads, and read by the daemon on every render.
**Options**: (a) in-place write + advisory `flock`; (b) atomic temp-file +
`os.replace`. **Decision**: (b), matching the supervisor's existing
`write_supervisor_status`. `os.replace` is atomic on POSIX, so a reader always
sees either the old or the new complete file — never a partial. Temp names carry
pid AND tid so no two writers share a temp path. Last-writer-wins is the desired
semantics (newest notice replaces older). No cross-process lock needed; a
`threading.Lock` guards only in-process rate-limit state.

## Success Criteria

- [ ] Ctrl+Z under the supervisor is dropped; no suspend; regression test proves it.
- [ ] Message file is atomically written, TTL-bounded; reader fails silent on
  absent/expired/malformed and never breaks the status line.
- [ ] Ctrl+Z guard posts a self-expiring notice via the channel.
- [ ] Thread safety documented in entry-point headers + architecture docs.
- [ ] All QA checks pass; daemon restarts RUNNING; 95%+ coverage on new code.

## Dependencies

- Touches the supervisor (brick-risk component). Keep `__version__` in lockstep
  with `version.py`; run the supervisor version-match QA test.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is SSoT for "when"). -->

- Plan created; scope confirmed with user: general message channel (Ctrl+Z is
  first consumer), thread-safe message files, thread safety made a first-class
  documented concern across all supervisor + status-line code.

## Notes & Updates

- Failsafe recovery cron: `2a71237b` (hourly at :37, non-durable, session-only).
