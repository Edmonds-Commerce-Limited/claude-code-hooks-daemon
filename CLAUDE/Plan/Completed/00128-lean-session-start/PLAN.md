# Plan 00128: Lean SessionStart — silent-when-healthy + verbose `check` command

**Status**: Complete
**Created**: 2026-06-17
**Owner**: Claude (Opus)
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded (TDD per handler)

## Overview

The SessionStart output is heavily bloated. Every new session prints a wall of
text: a 40-line dogfooding reminder, a container banner with indicators and
workflow tips, plus "all good" status lines from the config checker, hook
registration checker, and git filemode checker — none of which require any
action from the user.

The two genuinely useful advisories (daemon **version update** and **gitignore
safety**) already follow the correct model: they emit *only* when action is
needed and are otherwise silent. This plan makes every other SessionStart
advisory follow that same principle, and moves the verbose environment audit
(output tokens, bash working dir, container info, etc.) into an on-demand
`/hooks-daemon check` sub-command.

## Goals

- SessionStart emits nothing unless something actively needs the user's attention.
- Preserve the ability to surface the full verbose env/config audit on demand.
- Keep all check *logic* as the single source of truth (handlers), reused by the
  new command (DRY — no duplicated check code).

## Non-Goals

- Do NOT touch the `hello_world_*` handlers — they are an intentional dogfooding
  liveness signal and stay on (explicit user decision).
- Do NOT change `version_check` or `gitignore_safety_checker` — already correct.
- No changes to non-SessionStart events.

## Context & Background

Design decisions confirmed with the user:

1. **Verbose check home**: a `check` sub-command of the `/hooks-daemon` skill,
   backed by a new `cli check` daemon subcommand.
2. **hello_world handlers**: leave on (dogfooding liveness).
3. **dogfooding_reminder plugin**: trim from ~40 lines to a single line.

Sources of bloat (all SessionStart):

- `dogfooding_reminder` (project plugin, prio 2) — ~40 lines, restates CLAUDE.md.
- `yolo_container_detection` (lib) — banner + indicators + workflow tips.
- `optimal_config_checker` (lib) — full 6-setting report incl. all-passed.
- `hook_registration_checker` (lib) — "All checks passed" when healthy.
- `git_filemode_checker` (lib) — "core.fileMode=... (OK)" when healthy.

Already correct (the model): `version_check`, `gitignore_safety_checker`,
`suggest_status_line` — silent unless action needed.

## Tasks

### Phase 1: Quiet the SessionStart advisories (TDD, one handler at a time)

- [x] ✅ **Task 1.1**: `git_filemode_checker` — emit only when `core.fileMode=false`.
  Silent (empty context) on `true` and on not-a-git-repo / unknown.
- [x] ✅ **Task 1.2**: `hook_registration_checker` — suppress the "All checks
  passed" line; emit only when issues found (migration notice still emitted when
  a migration actually happened).
- [x] ✅ **Task 1.3**: `optimal_config_checker` — silent at SessionStart. Keep the
  `_enforce_settings_sync()` side-effect running silently; expose the check list
  for reuse by the `check` command. No report emitted on session start.
- [x] ✅ **Task 1.4**: `yolo_container_detection` — add `show_on_session_start`
  option (default `False`); when off, `matches()` returns False. Container info
  stays available via the status-line icon and the `check` command.
- [x] ✅ **Task 1.5**: `dogfooding_reminder` (project plugin) — trimmed `handle()`
  to a single concise reminder line; updated its co-located test.

### Phase 2: Verbose `check` command + skill sub-command (TDD)

- [x] ✅ **Task 2.1**: New `cli check` subcommand that aggregates a verbose
  env/config audit by reusing handler check logic: optimal-config (all 6 with
  why/fix/where/docs), container runtime, git filemode, hook registration.
  Single-source — calls existing handler methods/utils, no re-implemented checks.
- [x] ✅ **Task 2.2**: Wired `check` into the `/hooks-daemon` skill — added the
  `check` route (forwards via `daemon-cli.sh check`), a `check.md` doc, updated
  SKILL.md help text + `argument-hint` frontmatter.

### Phase 3: Integration & verification

- [x] ✅ **Task 3.1**: No config change needed — `show_on_session_start` defaults
  off, so the dogfood config needs no edit; no handler added/removed, so
  `.claude/HOOKS-DAEMON.md` is unchanged (no regen needed).
- [x] ✅ **Task 3.2**: Full QA `13/13` (8628 tests, 95.1% coverage); daemon
  restarted → RUNNING; live-verified a fresh SessionStart emits 2 lines and
  `cli check` emits the full verbose audit.
- [x] ✅ **Task 3.3**: Changed handlers' unit + acceptance-definition tests pass
  within the full suite; live socket verification done. (Full release acceptance
  playbook is a release-time gate, out of scope for this dev change.)

## Technical Decisions

### Decision 1: Quiet-by-behavior, not disable-by-config

**Context**: Two ways to silence a handler — disable it, or change it to stay
silent when healthy.
**Decision**: For `git_filemode_checker` and `hook_registration_checker`, change
behavior to emit only on problems (they must still run to catch real issues).
For `optimal_config_checker` and `yolo_container_detection` (no actionable
session-start state in the lean model), go silent/default-off but keep their
check logic intact for reuse by the `check` command. This keeps protection while
removing noise, and benefits all downstream installs.

### Decision 2: Handlers remain the single source of check logic

**Context**: The `check` command needs the same data the handlers compute.
**Decision**: The CLI command calls existing handler methods / shared utils
rather than duplicating checks — preserving DRY / single-source-of-truth.

## Success Criteria

- [x] A fresh SessionStart with a healthy, optimally-configured env prints only
  what genuinely needs action (nothing, in the healthy case) — version and
  gitignore advisories still fire when relevant.
- [x] `/hooks-daemon check` prints the full verbose env/config audit.
- [x] All QA checks pass; daemon restarts RUNNING; changed-handler tests pass.

## Notes & Updates

### 2026-06-17

- Plan created. Design forks resolved with user (skill sub-command; keep
  hello_world; trim dogfooding plugin to one line).

- Delivered. Phase 1 (quiet advisories) commit `4344d46`; Phase 2 (`cli check`

  - skill sub-command) commit `5490f24`; Black format fixup commit `a8fe650`.
    A fresh in-container SessionStart dropped from ~80 lines to 2 (the kept
    hello-world liveness line + the one-line dogfooding nudge). The verbose
    env/config audit (output tokens, bash working dir, container, fileMode, hook
    registration) now lives behind `/hooks-daemon check`. QA 13/13, daemon
    RUNNING, live-verified both directions.
