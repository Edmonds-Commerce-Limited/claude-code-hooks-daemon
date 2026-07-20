# Plan 00181: disk usage time bomb audit

**Status**: In Progress
**Created**: 2026-07-20
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A cleanup of `untracked/` surfaced a systemic pattern: the daemon writes many
files under its untracked directory, but **only one directory has a functioning
reaper**. Every other accumulator — archived transcripts, append-only JSONL
logs, the supervisor decision log, per-session sidecar/registry/capture files,
orphaned per-session daemon runtime files, and stale venvs — grows without any
rotation, retention cap, or age-based pruning. In a long-lived or high-churn
environment (CI fleets, multi-day container sessions, many compactions) these
consume unbounded disk with no automatic recovery.

A read-only audit (three parallel review agents + on-disk measurement)
confirmed the writers, located their code, and verified that **no shared
log-rotation or retention utility exists anywhere in the codebase**. This plan
records those findings and remediates them: introduce a single shared
retention/rotation primitive, apply it to every unbounded writer, and close the
reaper-invocation gaps so stale cross-session files are actually reaped.

## Goals

- Introduce ONE shared, config-driven retention/rotation utility (size cap +
  age/count pruning) — single source of truth, reused by every writer.
- Bound every confirmed unbounded writer (transcripts, the append-only JSONL
  logs, the supervisor decision log) with a sane default cap.
- Close the daemon-runtime-file reaper gaps so orphaned `daemon-*` files and
  per-session `thread-registry/` / `context-sidecar/` / `payload-capture/`
  files are reaped on a predictable schedule.
- Make stale-venv pruning happen automatically (not only during `upgrade` or
  manual `prune-venvs`), with a safe never-delete-current guarantee.
- Ship a `disk-usage` diagnostic CLI so operators can see accumulation and
  reclaim on demand.

## Non-Goals

- No change to what the daemon logs or archives (content/behaviour of handlers
  is out of scope — only lifecycle/retention of the files they write).
- No deletion of the current live venv, live daemon runtime files, or the
  in-progress session's transcripts under any circumstances (fail-safe).
- Not a rewrite of the transcript archiver or supervisor — only bounding their
  output.

## Audit Findings (read-only review — evidence for this plan)

Ranked worst-first. On-disk sizes are one snapshot; the concern is the growth
model (no reaper), not the current size.

| #   | Item                                                                                    | Writer (file:line)                                                             | Growth model                                             | Reaper today                                                                                                                                                                                          | Verdict      |
| --- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| 1   | Stale venvs `venv-{slug}-py{MM}-{fingerprint}` (~187 MB each)                           | install/`venv.sh` creation; prune in `venv.sh:716` `eager_cleanup_stale_venvs` | one venv per new Python fingerprint OR project-path slug | only on `upgrade` (`upgrade_version.sh:820`) or manual `prune-venvs` — never on daemon start                                                                                                          | BOMB         |
| 2   | `transcripts/*.json` (full transcript per compaction)                                   | `handlers/pre_compact/transcript_archiver.py:91`                               | one full-transcript snapshot per PreCompact, forever     | NONE (no cap/count/age)                                                                                                                                                                               | BOMB         |
| 3   | `logs/hooks/subagent_completions.jsonl`                                                 | `handlers/subagent_stop/subagent_completion_logger.py`                         | append per subagent stop (on by default)                 | NONE                                                                                                                                                                                                  | BOMB         |
| 4   | `logs/hooks/notifications.jsonl`                                                        | `handlers/notification/notification_logger.py`                                 | append per notification (on by default)                  | NONE                                                                                                                                                                                                  | BOMB         |
| 5   | `stop-events.jsonl`                                                                     | `handlers/stop/auto_continue_stop.py`                                          | append per stop event                                    | NONE                                                                                                                                                                                                  | BOMB         |
| 6   | `hook-errors.log`                                                                       | `core/front_controller.py`                                                     | append per handler error                                 | NONE                                                                                                                                                                                                  | BOMB         |
| 7   | supervisor `supervise/decision.log` (reached 2.9 MB / one 6.5h session)                 | `.claude/ccy/claude-supervise.py`                                              | append per idle tick                                     | NONE                                                                                                                                                                                                  | BOMB         |
| 8   | Orphaned `daemon-*.{sock,pid,socket-path,sock.start.lock}` (44 found, 11 dead sessions) | `daemon/paths.py` runtime files                                                | one set per dead session                                 | reaper EXISTS (`paths.py:1439` `cleanup_stale_daemon_files`) but BYPASSED — Plan 00127 reuse gate returns (`cli.py:362`) before the sweep (`cli.py:411`); 7-day `stale_file_days` floor spares recent | PARTIAL      |
| 9   | `thread-registry/`, `context-sidecar/`, `payload-capture/*.jsonl` (per-session)         | `multithread_indicator` / `context_sidecar` / `daemon/payload_capture.py`      | one file per session                                     | NONE — stale sweep is non-recursive, only `daemon-` prefix at untracked root                                                                                                                          | BOMB (small) |

**Genuinely bounded today (do not touch):** `version_check_cache.json`,
`gitignore_safety_cache.json`, `cleanup_status.json` (single-overwrite),
`background-processes.jsonl` (self-trims), `temp/hooks/` (reaped every
SessionEnd by `handlers/session_end/cleanup_handler.py` — the one functioning
reaper).

**Decisive structural fact:** a grep for `RotatingFileHandler` /
`TimedRotating` / `maxBytes` / `rotate` / `log_rotation` across
`src/claude_code_hooks_daemon/` returns **nothing** — there is no retention
primitive at all. Every writer independently opens-and-appends. That absence is
the root cause; a single shared utility is the proper fix.

## Tasks

### Phase 1: Shared retention primitive (TDD)

- [x] ✅ **Task 1.1**: `utils/retention.py` with `cap_log_file` (front-truncate a
  line log to a byte cap, keep newest whole lines) and `prune_directory`
  (bound a dir by max_count and/or max_age, newest kept, `protect` paths never
  deleted). 12 tests; best-effort (missing file/dir = no-op, per-entry IO errors
  logged not raised — explicit handling, not silent suppression). Budgets are
  parameters (no magic/policy in the module).
- [x] ✅ **Task 1.2 (revised)**: DECISION — instead of a global `daemon.retention`
  block, budgets are exposed as **per-handler `options.*`** (e.g.
  `transcript_archiver.options.max_archives`). The registry already injects any
  `options.<k>` as `self._<k>` (registry.py:379), so each writer gets a
  config-overridable budget with **zero new config plumbing** and per-writer
  granularity. Defaults are named module constants.
- [ ] ⬜ **Task 1.3**: Document the per-handler retention options in
  `HANDLER_REFERENCE.md`; add a `config-changes/v{X.Y.Z}.yaml` manifest entry at
  release time (recommended: true).

### Phase 2: Bound the append-only writers

- [x] ✅ **Task 2.1**: Size-cap applied to all four daemon append-only writers:
  `hook-errors.log` rotation backups (bound by count+age via `prune_directory`
  in `front_controller.log_error_to_file`), and `stop-events.jsonl`
  (`auto_continue_stop`), `notifications.jsonl` (`notification_logger`),
  `subagent_completions.jsonl` (`subagent_completion_logger`) each front-capped
  via `cap_log_file` with `retain_bytes` hysteresis. Tests first per writer
  (real-fs cap assertions). Full suite green (10433 passed, 95.2% coverage).
- [x] ✅ **Task 2.2**: Supervisor `decision.log` front-capped via an inline
  `DecisionLog._cap_if_needed` (mirrors `cap_log_file`; the standalone
  supervisor cannot import daemon modules). Called after every `write` /
  `write_noop`; keeps the newest `_DECISION_LOG_RETAIN_BYTES` (2 MB) of whole
  lines once the file passes `_DECISION_LOG_MAX_BYTES` (4 MB). A cap IO failure
  is reported to stderr and swallowed — never crashes a supervision tick, never
  loses the just-written line. 4 TDD cap tests; all 350 supervise tests pass
  (version-lockstep intact).

### Phase 3: Bound the archives + per-session dirs

- [x] ✅ **Task 3.1**: `transcript_archiver` now prunes `transcripts/` after each
  write via `prune_directory` — keeps the newest `max_archives` (default 40) and
  drops anything older than `max_archive_age_days` (default 14); the just-written
  archive is always newest so it survives. Config-overridable. 2 handler tests
  (count + age). Bounds the observed 57 MB offender.
- [x] ✅ **Task 3.2**: `paths.cleanup_stale_session_dirs` ages out the three
  per-session runtime subdirs (`thread-registry/`, `context-sidecar/`,
  `payload-capture/`) via the shared `prune_directory` primitive. Root cause:
  `thread_registry`/`context_sidecar` only SKIP stale entries at read time —
  they never unlink dead-session `{session_id}.json`, so one file leaks per
  session forever. Wired into the daemon start path alongside
  `cleanup_stale_daemon_files` (count folded into the cleanup-status total). 6
  TDD tests (per-subdir removal, fresh-preserved, mixed, now-override, missing
  dir/subdir no-ops). Daemon restart verified RUNNING.

### Phase 4: Close the reaper-invocation gaps

- [ ] ⬜ **Task 4.1**: Ensure `cleanup_stale_daemon_files` runs even on the
  Plan 00127 reuse path (move/duplicate the sweep before the early return, or
  run it unconditionally on start), preserving cross-project safety.
- [ ] ⬜ **Task 4.2**: Make stale-venv pruning run automatically on daemon start
  (guarded, never deletes the current fingerprint), reusing
  `eager_cleanup_stale_venvs`.

### Phase 5: Diagnostic + verification

- [ ] ⬜ **Task 5.1**: Add a `disk-usage` CLI subcommand that reports per-writer
  accumulation and what a prune would reclaim (dry-run by default).
- [ ] ⬜ **Task 5.2**: Full QA (`./scripts/qa/run_all.sh`), daemon restart
  verification, acceptance coverage for the new reapers.

## Dependencies

- Related: Plan 00127 (single-daemon reuse gate — the reason the daemon-file
  reaper is bypassed). Related: Plan 00180 (supervisor injection cap — same
  `decision.log` file touched in Task 2.2).

## Success Criteria

- [ ] A single shared retention utility exists and is the only place
  rotation/pruning logic lives (DRY; no per-writer copies).
- [ ] Every writer in the findings table with verdict BOMB is bounded by a
  default cap; a synthetic "write 10× the cap" test proves the file stops
  growing.
- [ ] Orphaned `daemon-*` files and per-session sidecar/registry/capture files
  are reaped on daemon start/session end within the configured window.
- [ ] Stale venvs are pruned automatically without ever removing the current
  fingerprint's venv.
- [ ] `disk-usage` CLI reports accumulation; all QA passes; daemon restarts
  RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Audit findings recorded (this document) at plan creation.
