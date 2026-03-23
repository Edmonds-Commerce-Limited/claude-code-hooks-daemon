# Plan 00092: CI Environment Graceful Degradation

**Status**: Not Started
**Created**: 2026-03-23
**Owner**: Claude
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Projects with hooks daemon installed break when Claude Code runs in CI environments (GitHub Actions, GitLab CI, etc.) for tasks like issue triage. The daemon isn't installed in CI, so hook scripts fail to start it, and the current error messaging tells the agent to restart the daemon — which is impossible in CI where there's no venv, no daemon package, and no config.

The fix: detect CI environments at the bash hook script level and degrade gracefully — log warnings but allow all operations to proceed. Hooks should be effectively transparent in CI.

## Goals

- Detect CI/CD environments (GitHub Actions, GitLab CI, CircleCI, Jenkins, etc.) reliably
- Allow all hook events to pass through without blocking in CI environments
- Emit clear log messages (stderr) so operators can see hooks are degraded
- Return valid JSON responses that don't trigger agent investigation loops
- Zero impact on normal (non-CI) operation

## Non-Goals

- Installing or running the daemon in CI environments
- Supporting a "CI mode" with selective handler execution
- Modifying handler logic — this is purely at the bash hook entry point layer
- Adding CI detection to Python code or handler logic

## Context & Background

### The Problem

1. User installs hooks daemon in their project (`.claude/hooks/` scripts + config)
2. Project is pushed to GitHub with `.claude/` committed
3. GitHub Actions workflow runs Claude Code for issue triage
4. Claude Code sees `.claude/settings.json` → loads hook scripts
5. Hook scripts source `init.sh` → tries `ensure_daemon()` → fails (no venv, no package)
6. `emit_hook_error()` outputs JSON telling agent to restart daemon
7. Agent sees error, tries to restart daemon, fails, enters investigation loop
8. Issue triage is blocked

### Current Behaviour

When daemon can't start (`init.sh` line 16-19 in each forwarder):
```bash
if ! ensure_daemon; then
    emit_hook_error "PreToolUse" "daemon_startup_failed" "..."
    exit 0
fi
```

For PreToolUse: returns `hookSpecificOutput` with error context (fail-open, but confusing)
For Stop/SubagentStop: returns `{"decision": "block"}` (hard block!)

### Desired Behaviour in CI

All events should return clean "no-op" responses:
- PreToolUse/PostToolUse: empty `hookSpecificOutput` (no context injection, no blocking)
- Stop/SubagentStop: no response or allow (don't block agent from stopping)
- SessionStart/SessionEnd/PreCompact: empty response
- Status: empty text

### Where to Intercept

The fix belongs in `init.sh` — before `ensure_daemon()` is ever called. If CI is detected, the forwarder scripts should short-circuit with a no-op response immediately. This means:

1. **`init.sh`**: Add CI detection function + export a flag
2. **Each forwarder script** (`pre-tool-use`, `post-tool-use`, etc.): Check flag before calling `ensure_daemon()`

OR (simpler):

1. **`init.sh`**: Override `ensure_daemon()` to always return 0 when CI detected, and override `send_request_stdin()` to return no-op JSON

The second approach is cleaner — forwarder scripts don't change at all.

## Technical Design

### CI Environment Detection

Check well-known CI environment variables. These are set by CI providers and are the standard detection mechanism:

```bash
is_ci_environment() {
    # GitHub Actions
    [[ -n "${GITHUB_ACTIONS:-}" ]] && return 0
    # GitLab CI
    [[ -n "${GITLAB_CI:-}" ]] && return 0
    # CircleCI
    [[ -n "${CIRCLECI:-}" ]] && return 0
    # Jenkins
    [[ -n "${JENKINS_URL:-}" ]] && return 0
    # Travis CI
    [[ -n "${TRAVIS:-}" ]] && return 0
    # Azure Pipelines
    [[ -n "${TF_BUILD:-}" ]] && return 0
    # Bitbucket Pipelines
    [[ -n "${BITBUCKET_PIPELINE_UUID:-}" ]] && return 0
    # AWS CodeBuild
    [[ -n "${CODEBUILD_BUILD_ID:-}" ]] && return 0
    # Google Cloud Build
    [[ -n "${BUILDER_OUTPUT:-}" ]] && return 0
    # Generic CI flag (many CI systems set this)
    [[ "${CI:-}" == "true" ]] && return 0

    return 1
}
```

### Graceful Degradation Strategy

When CI detected, override the two key functions in `init.sh`:

```bash
if is_ci_environment; then
    _CI_ENVIRONMENT=true
    echo "HOOKS DAEMON: CI environment detected - running in passthrough mode" >&2

    # Override ensure_daemon to no-op (don't try to start daemon)
    ensure_daemon() { return 0; }

    # Override send_request_stdin to return clean no-op JSON
    send_request_stdin() {
        # Read and discard stdin
        cat > /dev/null
        # Return empty/allow response
        echo '{}'
    }
fi
```

This approach means:
- Zero changes to any forwarder script
- Forwarder calls `ensure_daemon` → succeeds (no-op)
- Forwarder pipes to `send_request_stdin` → returns `{}` (empty, no blocking)
- Claude Code sees empty response → proceeds normally
- Warning logged to stderr for operators

### Response Format Consideration

Need to verify what Claude Code expects for each event type when there's no meaningful response. `{}` should work for all events — it means "no opinion" from the hook. But we should verify:

- PreToolUse: `{}` = allow (no block, no context)
- PostToolUse: `{}` = no context injection
- Stop/SubagentStop: `{}` = don't block stop
- SessionStart: `{}` = no context
- Status: needs `""` or `{"text": ""}` not `{}`

Status-line forwarder may need special handling since it returns plain text, not JSON.

### Opt-Out Mechanism

Projects might want to enforce hooks even in CI (e.g., security scanning CI jobs). Add an env var escape hatch:

```bash
# Force hooks daemon even in CI
HOOKS_DAEMON_FORCE=true
```

If `HOOKS_DAEMON_FORCE=true` is set, skip CI detection entirely.

## Tasks

### Phase 1: Research & Design Validation

- [ ] **Task 1.1**: Verify Claude Code's expected response format for each event type when hook returns `{}`
- [ ] **Task 1.2**: Check status-line forwarder — it may not go through `send_request_stdin`
- [ ] **Task 1.3**: Verify the `CI=true` generic flag is safe (some build tools set `CI=true` locally)
- [ ] **Task 1.4**: Review all 12 forwarder scripts to confirm they all use `ensure_daemon` + `send_request_stdin`

### Phase 2: TDD Implementation

- [ ] **Task 2.1**: Write tests for `is_ci_environment()` function
  - [ ] Test each CI provider env var individually
  - [ ] Test generic `CI=true` detection
  - [ ] Test no CI env vars → returns false
  - [ ] Test `HOOKS_DAEMON_FORCE=true` override
- [ ] **Task 2.2**: Write tests for graceful degradation behaviour
  - [ ] Test `ensure_daemon` returns 0 in CI mode
  - [ ] Test `send_request_stdin` returns `{}` in CI mode
  - [ ] Test stderr warning is emitted
  - [ ] Test status-line returns empty text in CI mode
- [ ] **Task 2.3**: Implement `is_ci_environment()` in `init.sh`
- [ ] **Task 2.4**: Implement function overrides when CI detected
- [ ] **Task 2.5**: Handle status-line forwarder (may need special case)

### Phase 3: Integration & Verification

- [ ] **Task 3.1**: Test with `GITHUB_ACTIONS=true` env var locally
  - [ ] Verify all hook events pass through
  - [ ] Verify no daemon startup attempts
  - [ ] Verify stderr warnings appear
  - [ ] Verify Claude Code sees no errors
- [ ] **Task 3.2**: Test with `HOOKS_DAEMON_FORCE=true` override
- [ ] **Task 3.3**: Test normal operation unaffected (no CI vars set)
- [ ] **Task 3.4**: Run full QA suite: `./scripts/qa/run_all.sh`
- [ ] **Task 3.5**: Restart daemon and verify: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Phase 4: Documentation

- [ ] **Task 4.1**: Document CI behaviour in relevant docs
- [ ] **Task 4.2**: Add `HOOKS_DAEMON_FORCE` env var to configuration reference

## Dependencies

- None — this is a standalone change at the bash script layer

## Technical Decisions

### Decision 1: Intercept at init.sh, not forwarder scripts

**Context**: Where to put the CI detection and passthrough logic.

**Options Considered**:
1. Each forwarder script checks CI and short-circuits — requires changing 12 files, duplication
2. `init.sh` detects CI and overrides `ensure_daemon`/`send_request_stdin` — single change point, zero forwarder changes
3. Python-level detection in daemon — doesn't help, daemon never starts in CI

**Decision**: Option 2 — override functions in `init.sh`. Single source of truth, zero changes to forwarders, leverages bash function override semantics.

### Decision 2: Use env vars, not filesystem detection

**Context**: How to detect CI environments.

**Options Considered**:
1. Check for CI-specific env vars (GITHUB_ACTIONS, GITLAB_CI, CI=true, etc.)
2. Check for filesystem indicators (/.dockerenv, /run/secrets, etc.)
3. Check for missing venv as proxy for CI

**Decision**: Option 1 — env vars. They're the standard mechanism, explicitly set by CI providers, and unambiguous. Filesystem checks overlap with legitimate container environments (YOLO mode). Missing venv is a symptom, not a cause.

### Decision 3: Warn but don't block

**Context**: What to do when CI is detected.

**Options Considered**:
1. Silent passthrough (no output at all)
2. Stderr warning + passthrough (operators see it in CI logs)
3. Stdout advisory context (agent sees it)

**Decision**: Option 2 — stderr warning. Operators reviewing CI logs can see hooks are degraded. Agent doesn't see stderr so won't enter investigation loops. Silent mode would make debugging harder.

### Decision 4: Opt-out via HOOKS_DAEMON_FORCE

**Context**: Some CI jobs might legitimately want hooks enforcement.

**Decision**: Add `HOOKS_DAEMON_FORCE=true` env var that skips CI detection entirely. This allows security-focused CI jobs to enforce hooks if daemon is installed in their CI image.

## Success Criteria

- [ ] Claude Code running in GitHub Actions with hooks daemon project proceeds without errors
- [ ] No daemon startup attempts in CI
- [ ] Stderr shows clear "CI environment detected - passthrough mode" message
- [ ] Normal (non-CI) operation is completely unaffected
- [ ] `HOOKS_DAEMON_FORCE=true` overrides CI detection
- [ ] All QA checks pass
- [ ] Daemon restarts successfully

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| `CI=true` set in non-CI environments | Med | Low | Also check for venv existence before degrading; document the behaviour |
| Status-line forwarder has different protocol | Low | Med | Research in Phase 1, handle specially if needed |
| Future CI providers not detected | Low | Med | Generic `CI=true` catches most; easy to add new vars |
| Operator doesn't see stderr warnings | Low | Med | CI systems typically capture stderr in logs |

## Notes & Updates

### 2026-03-23
- Plan created based on user report of GitHub Actions triage being broken
- Root cause: hooks daemon not installed in CI, error messaging triggers agent loops
