# Plan 00159: status writers thread safe tmp naming

**Status**: Not Started
**Created**: 2026-07-13
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Captures a low-severity finding from the v3.39.0 (Plan 00158) code-review gate so
it is not dropped into scrollback. The four status/signal writers that publish a
per-session file via the `tmp`-write + `os.replace` atomic pattern name their
temp file using only the process id: `f".{stem}.{os.getpid()}.tmp"`. Because the
daemon dispatches handlers on a single-process `ThreadPoolExecutor`
(`daemon/server.py` `loop.run_in_executor(None, ...)`), `os.getpid()` is
CONSTANT across every worker thread, so the only discriminator in the temp
filename is `stem` (the `session_id`).

For the documented cross-session threat model this is SAFE: two different
sessions have different `session_id`s, hence different stems, different temp
paths, and different final files — no corruption. The only theoretical gap is
SAME-session concurrency: if one `session_id` ever produced two concurrent
`handle()` calls, both threads would share temp path `.{stem}.{pid}.tmp` and
could tear each other's write (partial final file, or `os.replace` raising
`FileNotFoundError` because the source was already moved). Claude Code runs one
status-line subprocess per session at a time and waits for it, so this is
practically unreachable today, and the existing fail-open `except OSError`
absorbs any resulting error into "no segment". This is therefore a robustness
hardening, not a live bug.

## Goals

- Make each atomic writer's temp filename unique per writer regardless of the
  single-process/serialized-render assumption, so a future change that allows
  same-session concurrent renders cannot cause a torn write.
- Apply the fix consistently across all four sibling writers that share the
  `.{stem}.{pid}.tmp` convention (keep them uniform — it is a project pattern).

## Non-Goals

- No behaviour change for the cross-session case (already correct).
- No change to the reader filter (`.suffix == ".json"` already excludes every
  `.tmp` variant, so a longer temp suffix is a drop-in).
- Not a fix for any observed field failure — this is preventative hardening.

## Context & Background

Source of the finding (v3.39.0 code-review gate, code-reviewer verdict APPROVE,
Observation 1, confidence ~72%):

- `src/claude_code_hooks_daemon/handlers/status_line/thread_registry.py:113` —
  `tmp_path = registry_dir / f".{stem}.{os.getpid()}.tmp"` (introduced by Plan
  00158; this is the writer the finding was raised against).
- Sibling writers sharing the same `.{stem}.{pid}.tmp` convention (verify exact
  lines during implementation): `handlers/status_line/context_sidecar.py`
  (~line 176) and `handlers/pre_compact/compaction_signal.py` (~line 80).
- `daemon/server.py` (~lines 962/970) — the `run_in_executor(None, ...)` dispatch
  that makes `os.getpid()` constant across worker threads.

## Tasks

### Phase 1: Harden temp-file naming across the sibling writers

- [ ] ⬜ **Task 1.1**: Enumerate every writer using the `.{stem}.{pid}.tmp`
  convention and confirm each exact `file:line` (`thread_registry.py`,
  `context_sidecar.py`, `compaction_signal.py`, and any fourth surfaced by a
  repo-wide search for the pattern).
- [ ] ⬜ **Task 1.2**: Add a failing test per writer asserting two concurrent
  writes to the SAME stem do not leave a torn/partial final file (RED).
- [ ] ⬜ **Task 1.3**: Make temp names unique per writer — include
  `threading.get_ident()` in the suffix (or `tempfile.mkstemp(dir=...)`) —
  and get the tests green (GREEN), keeping the four writers uniform.
- [ ] ⬜ **Task 1.4**: Run QA (`./scripts/qa/llm_qa.py all`), restart the daemon,
  verify RUNNING.

### Phase 2: Supervisor `supervise()` stdin_fd type narrowing (v3.44.0 review)

- [ ] ⬜ **Task 2.1**: In `.claude/ccy/claude-supervise.py`, `supervise()`
  resolves `stdin_fd: int | None` at ~line 2602
  (`stdin_fd = stdin_fd if stdin_fd is not None else sys.stdin.fileno()`), but
  because the resolved value is captured by the `_on_winch` closure (~line 2656)
  Pyright discards the narrowing and reports `int | None` at every deref
  (~2647/2650/2652/2653/2656/2745/2760). Runtime-safe (line 2602 guarantees an
  int; live-tested) and OUTSIDE the mypy QA gate, so it never blocked. Remediation:
  assign the resolved fd to a fresh non-optional local
  (`resolved_stdin_fd: int = ...`) and use it at every subsequent site so the
  closure captures a non-None-typed variable. Optionally drop the unreachable
  `os._exit(127)` after `os.execvp` (~line 2642). Verify with the
  `tests/unit/supervise/` suite (claude-supervise.py is a standalone script, not
  daemon-loaded).

## Success Criteria

- [ ] All four writers use a per-writer-unique temp filename.
- [ ] New concurrency regression tests pass; existing suite stays green at 95%+.
- [ ] Daemon restarts RUNNING with the change.

## Notes & Updates

### 2026-07-13

- Plan scaffolded to capture v3.39.0 code-review Observation 1 (RELEASING.md
  "Never drop a finding"). The finding is low-severity and non-blocking; it did
  not gate the v3.39.0 release. Delivered as a follow-up so the review loop is
  closed rather than lost to scrollback.

### 2026-07-17

- Added Phase 2 capturing a v3.44.0 release code-review finding (RELEASING.md
  "Never drop a finding"): Pyright `stdin_fd: int | None` false-positives in the
  supervisor's `supervise()`, surfaced when the release bumped the supervisor
  `__version__`. Cosmetic (runtime-safe via the line-2602 guard, live-tested,
  outside the mypy QA gate) — v3.44.0 shipped without it. Fix is a trivial
  non-optional-local rename, deferred as low-priority hardening alongside the
  tmp-naming work.
