# Plan 00018: Fix Hooks Daemon Failure After Container/Host Environment Switching

**Status**: Complete
**Created**: 2026-01-30
**Revised**: 2026-01-30
**Completed**: 2026-01-30
**Owner**: Claude Opus 4.5
**Priority**: High
**Type**: Bug Fix
**GitHub Issue**: #15

## Overview

Fix ModuleNotFoundError when switching between container and host environments by surgically decoupling the hook invocation path from the venv Python. Instead of the originally proposed full rewrite (socat + uv run), this plan takes an incremental approach that fixes the root cause with minimal risk and zero new dependencies.

The original plan (see `PLAN-v1.md` and `CRITIQUE-v1.md`) proposed replacing ~140 lines of Python with `socat` and `uv run`. That approach was rejected due to: new hard dependencies (socat not installed by default), loss of granular error handling, fragile bash JSON escaping, and `uv run` introducing its own failure modes. This revised plan achieves the same outcome incrementally.

## Goals

- Eliminate venv Python dependency from per-invocation hook path
- Fix container/host switching failures (stale `.pth` files, Python version mismatches)
- Maintain granular error handling (5 distinct error types)
- Add zero new runtime dependencies
- Preserve cross-platform compatibility (Linux + macOS)

## Non-Goals

- Replace socket communication with socat (unnecessary, adds dependency)
- Use `uv run` at runtime (slow, network-dependent, new failure modes)
- Rewrite forwarder scripts (they work correctly as-is)
- Change the daemon's internal architecture

## Context & Background

When users switch between container (`/workspace/`) and host (`~/Projects/`) environments, the daemon fails because:

1. `PYTHON_CMD` points to a venv at an absolute path that doesn't exist in the other environment
2. Editable install `.pth` files contain absolute paths from the original install location
3. Python version may differ between environments (e.g., 3.11 in container, 3.13 on host)

The key insight is that the venv Python is only needed for two things in the hot path:
1. Computing socket/PID paths (lines 143-151 of init.sh)
2. Socket communication in `send_request_stdin()` (lines 277-377)

Neither of these requires any venv-installed packages — they use only Python stdlib (`socket`, `sys`, `json`, `hashlib`). The fix is to use system `python3` instead of venv Python for these operations.

## Tasks

### Phase 1: Bash Path Computation

Replace Python path generation with pure bash equivalents.

- [ ] **Task 1.1**: Implement bash `get_socket_path` equivalent
  - Replicate: `/tmp/claude-hooks-{name truncated to 20}-{md5 first 8}.sock`
  - Handle cross-platform md5: `md5sum` (Linux) vs `md5 -q` (macOS)
  - [ ] Write test script validating bash output matches Python output
  - [ ] Replace lines 143-146 of init.sh
  - [ ] Replace lines 148-151 of init.sh (PID path)
  - [ ] Remove `DAEMON_MODULE` variable (line 140)

- [ ] **Task 1.2**: Remove `PYTHON_CMD` from path computation
  - `PYTHON_CMD` is no longer needed at init-time for path generation
  - Keep `PYTHON_CMD` for now (still used by `start_daemon` and `emit_hook_error`)

### Phase 2: System Python Socket Client

Replace venv Python with system `python3` for socket communication.

- [ ] **Task 2.1**: Change `send_request_stdin()` to use `python3` instead of `$PYTHON_CMD`
  - The embedded Python uses only stdlib: `socket`, `sys`, `json`, `subprocess`
  - Replace `$PYTHON_CMD -c "..."` with `python3 -c "..."` on line 277
  - Remove the `subprocess.run` call to `error_response` module (venv dependency)
  - Inline the error JSON generation using only stdlib `json.dumps()`
  - [ ] Verify all 5 error types are preserved
  - [ ] Test with Python 3.11, 3.12, 3.13

- [ ] **Task 2.2**: Update `emit_hook_error()` to use `jq` instead of venv Python
  - Replace lines 47-49 (Python error_response module call) with `jq` command
  - `jq` is already a required dependency
  - Use: `jq -n --arg event "$1" --arg type "$2" --arg details "$3" '{hookSpecificOutput: {hookEventName: $event, additionalContext: ...}}'`
  - Keep bash fallback for when jq is unavailable
  - Handle Stop/SubagentStop event special case in bash/jq

### Phase 3: Venv Health Validation

Add fail-fast validation so daemon startup gives clear errors instead of cryptic ModuleNotFoundError.

- [ ] **Task 3.1**: Add venv health check function to init.sh
  - Check venv Python binary exists and is executable
  - Check venv Python version matches what created it
  - Check key packages are importable: `$PYTHON_CMD -c "import claude_code_hooks_daemon" 2>/dev/null`
  - Return clear error message if any check fails

- [ ] **Task 3.2**: Integrate health check into `start_daemon()`
  - Before starting daemon, validate venv
  - On failure: emit actionable error telling user to run `uv sync` or reinstall
  - Do NOT auto-repair (explicit is better than implicit)

- [ ] **Task 3.3**: Add `--repair` flag to daemon CLI
  - `python -m claude_code_hooks_daemon.daemon.cli repair` runs `uv sync`
  - Provides a one-command fix the agent can suggest when venv is broken

### Phase 4: Cleanup and Documentation

- [ ] **Task 4.1**: Remove `PYTHON_CMD` export if no longer needed in init.sh
  - After phases 1-2, check if `PYTHON_CMD` is still used anywhere in init.sh
  - It will still be needed for `start_daemon()` (line 217) — keep it but don't export
  - Or: switch `start_daemon()` to also use system python3 if the daemon CLI can bootstrap itself

- [ ] **Task 4.2**: Update documentation
  - Update CLAUDE.md if architecture description changes
  - Update SELF_INSTALL.md if path resolution changes
  - Update LLM-INSTALL.md if install prerequisites change

- [ ] **Task 4.3**: Run full QA suite
  - `./scripts/qa/run_all.sh`
  - Verify 95%+ coverage maintained
  - Test in both container and host environments

## Technical Decisions

### Decision 1: System python3 vs socat for socket communication
**Context**: Need to remove venv dependency from socket client
**Options**:
1. `socat` — fast (2ms), but new hard dependency not installed by default
2. System `python3` — slightly slower (~30ms), but universally available, preserves error granularity
3. Bash `/dev/tcp` — no Unix socket support

**Decision**: System `python3`. Zero new dependencies, preserves all 5 error types, cross-platform. The 30ms overhead is acceptable for a hook invocation.

### Decision 2: jq vs bash for error JSON generation
**Context**: `emit_hook_error()` currently uses venv Python module
**Options**:
1. Pure bash string interpolation — fragile, misses escape characters
2. `jq` — correct JSON generation, already a dependency
3. System `python3 -c "import json; ..."` — correct but slower for error path

**Decision**: `jq` with bash fallback. Correct, fast, already required.

### Decision 3: Venv repair strategy
**Context**: When venv is broken after environment switch, what happens?
**Options**:
1. Auto-repair with `uv sync` — implicit, may surprise users, network dependency
2. Fail-fast with actionable error — explicit, user controls repair
3. `uv run` at runtime — slow, network-dependent

**Decision**: Fail-fast with actionable error. Add `--repair` CLI command for easy fix. Explicit is better than implicit.

## Success Criteria

- [ ] Hook invocations work without venv Python in the hot path
- [ ] Switching between container and host environments doesn't break hooks
- [ ] All 5 error types preserved in socket communication
- [ ] Zero new runtime dependencies added
- [ ] Broken venv produces clear, actionable error message
- [ ] All QA checks pass (95%+ coverage)
- [ ] Works on both Linux and macOS

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| System python3 not available | High | Very Low | Python 3 is a prerequisite; fail-fast check at init |
| md5sum platform differences | Low | Medium | Detect platform, use md5sum or md5 -q accordingly |
| Stop event special-case missed in jq | Medium | Low | Port logic carefully, test explicitly |
| start_daemon still needs venv Python | Low | Certain | Acceptable — daemon startup is cold path, venv is validated first |

## Dependencies

- Supersedes original Plan 00018 approach (see CRITIQUE-v1.md)
- GitHub Issue #15

## Notes & Updates

### 2026-01-30
- Original plan (socat + uv run rewrite) reviewed and superseded
- Critique documented in CRITIQUE-v1.md
- Revised plan uses incremental, surgical approach with zero new dependencies
