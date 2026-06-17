# Plan 00128: Lean SessionStart — silent-when-healthy + verbose `check` command

**Status**: In Progress
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

- [ ] ⬜ **Task 3.1**: Update `.claude/hooks-daemon.yaml` only if a new option needs
  surfacing (yolo `show_on_session_start`). Regenerate `.claude/HOOKS-DAEMON.md`.
- [ ] ⬜ **Task 3.2**: Full QA (`./scripts/qa/llm_qa.py all`), daemon restart →
  RUNNING, live-verify a fresh SessionStart is lean and `check` is verbose.
- [ ] ⬜ **Task 3.3**: Acceptance tests for changed handlers + new command pass.

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

- [ ] A fresh SessionStart with a healthy, optimally-configured env prints only
  what genuinely needs action (nothing, in the healthy case) — version and
  gitignore advisories still fire when relevant.
- [ ] `/hooks-daemon check` prints the full verbose env/config audit.
- [ ] All QA checks pass; daemon restarts RUNNING; acceptance tests pass.

## Notes & Updates

### 2026-06-17

- Plan created. Design forks resolved with user (skill sub-command; keep
  hello_world; trim dogfooding plugin to one line).
