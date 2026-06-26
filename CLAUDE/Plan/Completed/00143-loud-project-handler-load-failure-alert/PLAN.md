# Plan 00143: Loud Project-Handler Load-Failure Alert

**Status**: Complete
**Created**: 2026-06-26
**Owner**: Claude (Opus)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration
**Recovery cron**: `eb117d72` (non-durable, hourly :37)

## Overview

When project-level handlers (`.claude/project-handlers/`) fail to load — e.g. a daemon
upgrade introduces a new required abstract method (`get_claude_md`, required since v2.30.0)
that an older handler does not implement — the daemon does the safe thing and skips the broken
handlers, keeping working ones active. But it does so **silently**: the skip is only a
load-time `logger.warning` line that nobody sees at session start. An agent (or human) can then
work an entire session believing protections are live when they are not — *fail-safe
enforcement with fail-silent signalling*, which manufactures false confidence.

This plan fixes the **observability** defect (not the enforcement, which is correct). The
running daemon already knows which handlers failed; we persist that fact and surface it loudly
at every session start until it is fixed and the daemon restarted, plus expose it through the
health/status CLI and gate upgrades on it.

Source bug report: `untracked/hooks-daemon-silent-fail-project-handlers.md`.

## Goals

- Persist project-handler load failures (filename + reason) recorded by the **running** daemon
  to a state file, rewritten on every daemon startup so it always reflects current reality.
- A new SessionStart handler injects a **loud, recurring** "PROJECT PROTECTION DEGRADED" alert
  every session while any failure persists; stays silent when clean (Lean SessionStart).
- `status` / `health` / `check` CLI surface a degraded signal (non-zero where appropriate) when
  `loaded < discovered` for project handlers.
- Upgrade scripts run `validate-project-handlers` post-upgrade and warn loudly if the upgrade
  dropped any previously-working handler.

## Non-Goals

- Changing the fail-safe skip behaviour (broken handlers MUST keep being skipped, not crash).
- Auto-fixing broken handlers.
- Persisting state across machines / any networked reporting.

## Context & Background

Key code (mapped during planning):

- `src/.../handlers/project_loader.py` — `discover_handlers()` accumulates `load_failures`
  (filenames only) and logs a warning (lines 277-285). Reasons are logged per-file but not
  returned. No persisted state.
- `src/.../daemon/controller.py` — `_load_project_handlers()` (line 326) resolves the handlers
  path and calls `discover_handlers()`. This is where the running daemon learns the failures.
- `src/.../handlers/session_start/hook_registration_checker.py` — the pattern to mirror
  (live audit at new-session start, loud context when issues, silent when clean,
  `get_claude_md`, acceptance tests).
- `src/.../daemon/cli.py` — `cmd_status` (606), `cmd_health` (782), `cmd_check` (850),
  `cmd_validate_project_handlers` (2434).
- `scripts/upgrade_version.sh` step 16 runs `run_post_install_checks` — does NOT validate
  project handlers.

**State file location**: daemon untracked dir via `ProjectContext.daemon_untracked_dir()`
(security rule: never `/tmp`). Filename `project-handler-load-failures.json`.

## Technical Decisions

### Decision 1: Persisted daemon state vs live re-discovery

**Context**: The SessionStart handler needs to know which project handlers failed.
**Options**:

1. Live re-discovery in the handler (re-scan disk each session).
2. Persist the running daemon's actual `load_failures` at startup; handler reads the file.

**Decision**: Option 2. The persisted state reflects what the **running daemon** actually
failed to load. If a user fixes a handler on disk but does not restart, live re-discovery would
falsely report "all good" while the daemon is still running without the handler. Persisted state
correctly keeps alerting until a restart rewrites the file — and "restart the daemon" is exactly
the remediation. Always rewriting on startup (empty failures → empty/removed file) prevents
staleness.

### Decision 2: Capture failure reasons without breaking callers

**Context**: `discover_handlers()` returns only successful `(EventType, Handler)` tuples; the
reasons are logged and discarded.
**Decision**: Add a richer static method `discover_handlers_with_failures()` returning a small
`ProjectHandlerDiscovery` dataclass (`handlers`, `failures: list[ProjectHandlerLoadFailure]`).
`discover_handlers()` delegates to it and returns just the handlers (backward compatible).
Controller calls the richer method to persist failures. DRY, no caller breakage.

### Decision 3: Single source of truth for the state file

**Context**: handler, CLI status/health/check all need to read the same state.
**Decision**: A dedicated module `daemon/project_handler_health.py` owns the path, the
dataclasses, and read/write/clear functions. Handler + CLI both import from it. No duplicated
path logic or JSON parsing.

## Tasks

### Phase 1: Failure capture + persistence (data layer) ✅

- [x] ✅ **Task 1.1**: `ProjectHandlerLoadFailure` + `ProjectHandlerDiscovery` dataclasses
  and `discover_handlers_with_failures()` in `project_loader.py`; `discover_handlers()`
  delegates and stays backward compatible.
- [x] ✅ **Task 1.2**: `daemon/project_handler_health.py` — state-file path (daemon untracked
  dir), `write_load_failures()`, `read_load_failures()`, `clear_load_failures()`. Always
  rewrite/clear on write so the file reflects the running daemon.
- [x] ✅ **Task 1.3**: Wired `controller._load_project_handlers()` to capture failures and
  persist via the health module on every startup (write even when empty → cleared); persists
  before the empty-handler early return. Integration tests added.

### Phase 2: Loud SessionStart alert (new handler) ✅

- [x] ✅ **Task 2.1**: Added `HandlerID.PROJECT_HANDLER_LOAD_CHECKER` + `Priority` (50).
- [x] ✅ **Task 2.2**: New handler `session_start/project_handler_load_checker.py` — reads
  state, loud alert when failures, silent when clean; `get_claude_md`; `get_acceptance_tests`.
- [x] ✅ **Task 2.3**: Registered in session_start package + `.claude/hooks-daemon.yaml`.
- [x] ✅ **Task 2.4**: Daemon restart + verified alert fires against a synthetic broken handler
  (missing-get_claude_md) and clears after removal + restart.

### Phase 3: CLI degraded signal ✅

- [x] ✅ **Task 3.1**: `status` reports a loud DEGRADED block when failures present.
- [x] ✅ **Task 3.2**: `health` returns non-zero (and reports detail) when degraded.
- [x] ✅ **Task 3.3**: `check` includes a project-handler-health section.

### Phase 4: Upgrade-time gate ✅

- [x] ✅ **Task 4.1**: `upgrade_version.sh` Step 16.5 runs `validate-project-handlers`
  post-upgrade; loud `print_warning` (not hard-fail) with restart guidance if failures
  detected. Contract test pins it (invoked, loud, non-fatal, restart guidance).

### Phase 5: Integration, QA, docs ✅

- [x] ✅ **Task 5.1**: Full QA `./scripts/qa/llm_qa.py all` → 13/13 PASSED (9126 tests, 95.2%
  coverage); daemon restart RUNNING.
- [x] ✅ **Task 5.2**: Regenerated docs → `.claude/HOOKS-DAEMON.md` + CLAUDE.md `<hooksdaemon>`
  block include the new handler.
- [x] ✅ **Task 5.3**: Acceptance test provided via the handler's `get_acceptance_tests()`
  (CONTEXT test asserting the `PROJECT PROTECTION DEGRADED` banner); picked up by the playbook
  generator.
- [x] ✅ **Task 5.4**: Config-changes manifest `UNRELEASED/config-changes/v3.31.0.yaml` (added
  entry). The handler ships **on by default (opt-out)** so it is active automatically — no
  `recommended` promotion needed (mirrors `root_recursion_guard`); the original plan's
  `recommended: true` assumption was superseded by the on-by-default decision.
- [x] ✅ **Also (surfaced by QA)**: added the handler to the default config template
  (`init_config.py`) and the example config (`.claude/hooks-daemon.yaml.example`) to satisfy
  config-coverage tests; added three justified `error_hiding_exclusions.json` entries for the
  best-effort persistence/clear log-and-continue patterns.

## Success Criteria

- [x] A broken project handler produces a loud session-start alert EVERY session until fixed +
  daemon restarted.
- [x] `status`/`health`/`check` mechanically report the degraded state.
- [x] Upgrade warns if it dropped a previously-working handler.
- [x] Silent when there are zero failures (no new noise on healthy projects).
- [x] All QA passes; daemon restarts RUNNING; 95%+ coverage on new code.

## Notes & Updates

### 2026-06-26

- Plan created. Recovery cron `eb117d72` set up. Architecture mapped; design decisions recorded.
- **Complete.** Delivered across commits `7fdee2c` (plan), `384f353` (Phase 1 — capture +
  persist), `7cac2b1` (Phase 2 — loud SessionStart alert), `43b8dc1` (Phase 3 — CLI signal),
  `a37834d` (Phase 4 — upgrade gate), `bf183f9` (Phase 5 — docs/config/manifest/QA). Full QA
  13/13 PASSED (9126 tests, 95.2% coverage); daemon restart verified RUNNING. Loud alert
  verified end-to-end against the live daemon (fires on a synthetic missing-`get_claude_md`
  handler, clears after fix + restart).
