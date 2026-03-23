# Plan 00092: CI Environment Graceful Degradation

**Status**: Complete (2026-03-23)
**Created**: 2026-03-23
**Owner**: Claude
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Projects with hooks daemon installed break when Claude Code runs in CI environments (GitHub Actions, GitLab CI, etc.) for tasks like issue triage. The daemon isn't installed in CI, so hook scripts fail to start it, and the current error messaging tells the agent to restart the daemon — which is impossible in CI where there's no venv, no daemon package, and no config.

The fix: parse the hooks daemon config (`hooks-daemon.yaml`) for a `ci_enabled` setting and degrade gracefully based on that config. Default behaviour is fail-open with one-time noise. When `ci_enabled: true` is set, fail closed with a loud STOP message.

## Goals

- Parse `hooks-daemon.yaml` for `ci_enabled` config setting to control CI behaviour
- Default (no `ci_enabled`): fail open — warn once to stderr, write state file, then silently passthrough
- `ci_enabled: true`: fail closed — hard deny/block with clear STOP message telling agent to report hooks daemon needs installing
- State file prevents repeated noise on every hook call
- Logic only activates when daemon cannot start — zero impact on normal operation

## Non-Goals

- Environment variable-based CI detection (explicitly rejected — config-based approach chosen)
- Installing or running the daemon in CI environments
- Supporting a "CI mode" with selective handler execution
- Modifying handler logic — this is purely at the bash hook entry point layer

## Context & Background

### The Problem

1. User installs hooks daemon in their project (`.claude/hooks/` scripts + config)
2. Project is pushed to GitHub with `.claude/` committed
3. GitHub Actions workflow runs Claude Code for issue triage
4. Claude Code sees `.claude/settings.json` -> loads hook scripts
5. Hook scripts source `init.sh` -> tries `ensure_daemon()` -> fails (no venv, no package)
6. `emit_hook_error()` outputs JSON telling agent to restart daemon
7. Agent sees error, tries to restart daemon, fails, enters investigation loop
8. Issue triage is blocked

### Solution: Config-Based Graceful Degradation

Two modes controlled by `ci_enabled` in `hooks-daemon.yaml`:

**Default (fail open):**
1. First call: `ensure_daemon()` fails -> warn to stderr -> write `.hooks-passthrough` state file -> return advisory context
2. Subsequent calls: detect state file -> silently passthrough (`{}`) with no noise

**`ci_enabled: true` (fail closed):**
1. Every call: `ensure_daemon()` fails -> hard deny/block with STOP message
2. No state file written — every call blocks
3. Message clearly instructs agent to stop and report hooks daemon needs installing

## Technical Design

### Config Parsing

Simple grep-based config check (no Python/yq dependency needed in CI):

```bash
_is_ci_enforced() {
    local config_file="$PROJECT_PATH/.claude/hooks-daemon.yaml"
    [[ -f "$config_file" ]] && grep -qE '^\s+ci_enabled:\s*true' "$config_file"
}
```

### State File Pattern

```bash
_passthrough_flag_path() {
    echo "$HOOKS_DAEMON_ROOT_DIR/untracked/.hooks-passthrough"
}
```

### Function Override Pattern

When entering passthrough mode, `send_request_stdin()` is redefined to consume stdin and return `{}`:

```bash
_enter_passthrough_mode() {
    send_request_stdin() {
        cat > /dev/null
        echo '{}'
    }
    export -f send_request_stdin
}
```

### ensure_daemon() Flow

```
ensure_daemon() called
  -> daemon running? return 0 (normal path)
  -> state file exists? enter passthrough, return 0
  -> try start_daemon -> success? clean state file, return 0
  -> ci_enabled: true? set CI_ENFORCED flag, return 1
  -> default: warn stderr, write state file, advisory passthrough, return 0
```

### emit_hook_error() CI Enforcement

When `_HOOKS_DAEMON_CI_ENFORCED=true`:
- PreToolUse: `{"decision": "deny", "reason": "STOP - DO NOT PROCEED..."}`
- Stop/SubagentStop: `{"decision": "block", "reason": "..."}`
- Other events: `{"hookSpecificOutput": {...}}` with loud STOP context

## Tasks

### Phase 1: Research & Design
- [x] ✅ **Task 1.1**: Analyse current `init.sh` behaviour when daemon fails
- [x] ✅ **Task 1.2**: Design config-based approach (replaced env var approach per user feedback)
- [x] ✅ **Task 1.3**: Design state file pattern for one-time noise

### Phase 2: TDD Implementation
- [x] ✅ **Task 2.1**: Write tests for default fail-open behaviour (6 tests)
  - [x] First call returns advisory context with INACTIVE message
  - [x] First call logs warning to stderr
  - [x] State file created on first failure
  - [x] Second call is silent passthrough (`{}`)
  - [x] `ci_enabled: false` behaves same as default
  - [x] Default mode never blocks any event type
- [x] ✅ **Task 2.2**: Write tests for `ci_enabled: true` fail-closed behaviour (5 tests)
  - [x] PreToolUse denied with STOP message
  - [x] Stop events blocked
  - [x] No state file created
  - [x] Every call blocks (no bypass)
  - [x] Message tells agent to stop working
- [x] ✅ **Task 2.3**: Write test for passthrough recovery (1 test)
  - [x] State file persists when daemon still unavailable
- [x] ✅ **Task 2.4**: Implement `_is_ci_enforced()`, `_passthrough_flag_path()`, `_enter_passthrough_mode()` in `init.sh`
- [x] ✅ **Task 2.5**: Modify `ensure_daemon()` with state file and CI enforcement logic
- [x] ✅ **Task 2.6**: Modify `emit_hook_error()` with CI enforcement responses

### Phase 3: Integration & Verification
- [x] ✅ **Task 3.1**: All 12 tests pass
- [x] ✅ **Task 3.2**: Full QA suite passes (8/8 checks)
- [x] ✅ **Task 3.3**: Daemon restarts successfully
- [x] ✅ **Task 3.4**: Update `hooks-daemon.yaml.example` with `ci_enabled` documentation

### Phase 4: Documentation
- [x] ✅ **Task 4.1**: Document `ci_enabled` in example config with comments explaining behaviour

## Dependencies

- None — standalone change at the bash script layer

## Technical Decisions

### Decision 1: Config-based, not env var-based detection

**Context**: How to control CI behaviour.

**Options Considered**:
1. Check CI-specific env vars (GITHUB_ACTIONS, GITLAB_CI, CI=true, etc.)
2. Parse `hooks-daemon.yaml` for a `ci_enabled` setting

**Decision**: Option 2 — config-based. User explicitly rejected env var approach. Config gives explicit control per-project and avoids false positives from env vars that may be set in non-CI contexts (e.g., `CI=true` in local builds).

### Decision 2: State file for one-time noise

**Context**: Default mode should warn but not spam every hook call.

**Decision**: Write `.hooks-passthrough` state file in `untracked/` on first failure. Subsequent calls detect the file and silently passthrough. State file is cleaned up if daemon successfully starts later.

### Decision 3: Function override pattern

**Context**: How to make forwarder scripts passthrough without changing them.

**Decision**: Redefine `send_request_stdin()` inside `ensure_daemon()` so forwarder scripts continue to pipe to it but get `{}` back. Zero changes to any forwarder script.

### Decision 4: CI enforced blocks every call

**Context**: When `ci_enabled: true` is set, should we use a state file?

**Decision**: No state file for CI enforced mode. Every call gets a hard deny/block with STOP message. This ensures the agent sees the error and stops immediately rather than silently degrading.

## Success Criteria

- [x] Claude Code running in CI with hooks daemon project proceeds without errors (default mode)
- [x] `ci_enabled: true` hard-blocks with clear STOP message
- [x] State file prevents repeated noise in default mode
- [x] Normal (non-CI) operation completely unaffected (logic only fires when daemon fails)
- [x] All 12 tests pass
- [x] All QA checks pass (8/8)
- [x] Daemon restarts successfully

## Files Changed

- `init.sh` — Added `_is_ci_enforced()`, `_passthrough_flag_path()`, `_enter_passthrough_mode()`, modified `ensure_daemon()` and `emit_hook_error()`
- `tests/unit/test_ci_passthrough.py` — 12 new tests (3 test classes)
- `.claude/hooks-daemon.yaml.example` — Documented `ci_enabled` option

## Notes & Updates

### 2026-03-23
- Plan created based on user report of GitHub Actions triage being broken
- Initial design used env var detection — user rejected this approach
- Redesigned around config-based `ci_enabled` setting
- Implementation complete: 12 tests pass, 8/8 QA checks pass, daemon restarts
- Committed as `d07647b`: "Add: CI environment graceful degradation for hooks daemon"
