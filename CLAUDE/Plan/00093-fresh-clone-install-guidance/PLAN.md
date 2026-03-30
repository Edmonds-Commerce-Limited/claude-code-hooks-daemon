# Plan 00093: Fresh-Clone Install Guidance

**Status**: Not Started
**Created**: 2026-03-30
**Owner**: TBD
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

When a hooks-daemon-based project is freshly cloned, the committed `.claude/hooks/` scripts and `hooks-daemon.yaml` config are present, but `.claude/hooks-daemon/` (the daemon installation) is absent. Currently the daemon startup failure falls through to `emit_hook_error()` which outputs:

> "HOOKS DAEMON: Not currently running… TO FIX: Run: `python -m claude_code_hooks_daemon.daemon.cli restart`"

This is **wrong advice** for a fresh clone — the daemon has never been installed and `restart` will fail. The LLM needs to be guided to read and follow `CLAUDE/LLM-INSTALL.md` instead.

CI environments are already handled:
- `ci_enabled: false` (default) + CI env vars → silent passthrough mode ✅
- `ci_enabled: true` → hard STOP with install instructions ✅

The gap is **non-CI environments where the daemon is not installed** — the user/LLM sees confusing "restart" advice instead of "install first" guidance.

## Goals

- Detect "daemon not installed" vs "daemon installed but not running" in `init.sh`
- Show clear install guidance (pointing to `CLAUDE/LLM-INSTALL.md`) for the not-installed case
- Keep "restart" guidance for the installed-but-not-running case unchanged
- Fail-open (advisory, not blocking) for PreToolUse — LLM must be able to read files and run install commands
- Block Stop/SubagentStop (same as current not-running behaviour — don't let session end silently with safety inactive)

## Non-Goals

- Changing CI behaviour (already correct)
- Auto-installing the daemon (user must drive installation)
- Suppressing repeated warnings per-session (keep it noisy — safety is inactive)
- Any Python daemon changes (pure `init.sh` shell change)

## Context & Background

### Current flow (fresh clone, non-CI)

```
session-start script
  → source init.sh
  → ensure_daemon()
      → is_daemon_running() → false (no PID file)
      → start_daemon()
          → validate_venv() → FAIL ($PYTHON_CMD doesn't exist at .claude/hooks-daemon/untracked/venv/bin/python)
          → return 1
      → _is_ci_enforced() → false
      → _is_ci_environment() → false
      → return 1   ← exits without setting any flag
  → emit_hook_error "SessionStart" "daemon_startup_failed" "Failed to start hooks daemon..."
      → _HOOKS_DAEMON_CI_ENFORCED == false  → "Not currently running" message with restart advice ← WRONG
```

### Existing pattern to follow

`_HOOKS_DAEMON_CI_ENFORCED` flag is set in `ensure_daemon()` before returning 1, then read in `emit_hook_error()` to branch message content. We add a parallel `_HOOKS_DAEMON_NOT_INSTALLED` flag with the same pattern.

### Detection logic

```bash
_is_daemon_installed() {
    # Daemon is "installed" if its root dir and venv Python both exist
    [[ -d "$HOOKS_DAEMON_ROOT_DIR" ]] && [[ -f "$PYTHON_CMD" ]]
}
```

This correctly handles:
- Fresh clone (no `hooks-daemon/` dir at all) → not installed
- Broken partial install (dir exists, venv missing) → not installed → guide to reinstall
- Installed but crashed → installed, fail → "restart" advice (unchanged)

## Tasks

### Phase 1: init.sh Changes

- [ ] ⬜ **Task 1.1**: Add global flag `_HOOKS_DAEMON_NOT_INSTALLED=false` near `_HOOKS_DAEMON_CI_ENFORCED=false` (line ~21)

- [ ] ⬜ **Task 1.2**: Add `_is_daemon_installed()` helper function (after `_is_ci_environment()`, around line 445):
  ```bash
  _is_daemon_installed() {
      [[ -d "$HOOKS_DAEMON_ROOT_DIR" ]] && [[ -f "$PYTHON_CMD" ]]
  }
  ```

- [ ] ⬜ **Task 1.3**: Update `ensure_daemon()` non-CI failure branch (around line 555) to detect not-installed state before returning 1:
  ```bash
  # Non-CI environment: fail with error so agent sees it and can act
  # Distinguish not-installed (fresh clone) from installed-but-broken
  if ! _is_daemon_installed; then
      _HOOKS_DAEMON_NOT_INSTALLED=true
  fi
  return 1
  ```

- [ ] ⬜ **Task 1.4**: Add "not installed" message branch in `emit_hook_error()` between the CI-enforced branch and the standard branch (around line 51):
  ```bash
  elif [[ "$_HOOKS_DAEMON_NOT_INSTALLED" == "true" ]]; then
      context_msg=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s' \
          "HOOKS DAEMON: Not installed" \
          "" \
          "This project uses the Claude Code Hooks Daemon for safety enforcement," \
          "but the daemon is not installed in this environment." \
          "" \
          "ALL safety handlers, code quality checks, and workflow enforcement are INACTIVE." \
          "" \
          "TO INSTALL — read and follow the guide (do not improvise):" \
          "  CLAUDE/LLM-INSTALL.md" \
          "" \
          "After installing, the daemon starts automatically on the next hook event.")
  ```

  For the JSON output section (around line 92), add corresponding branch:
  - PreToolUse: fail-open advisory context (same as standard not-running, but "not installed" message)
  - Stop/SubagentStop: block (same as standard not-running)

- [ ] ⬜ **Task 1.5**: Verify shellcheck passes on the modified `init.sh`
  ```bash
  shellcheck .claude/init.sh
  ```

### Phase 2: Verification

- [ ] ⬜ **Task 2.1**: Daemon restart verification — confirm daemon still starts cleanly
  ```bash
  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
  $PYTHON -m claude_code_hooks_daemon.daemon.cli status
  # Expected: RUNNING
  ```

- [ ] ⬜ **Task 2.2**: Manual test — simulate not-installed by checking what `emit_hook_error` outputs with flag set:
  ```bash
  # Source init.sh, set flag, call emit_hook_error, verify output JSON
  bash -c '
    source .claude/init.sh 2>/dev/null || true
    _HOOKS_DAEMON_NOT_INSTALLED=true
    emit_hook_error "SessionStart" "daemon_startup_failed" "test"
  ' | python3 -m json.tool
  # Expected: hookSpecificOutput with "Not installed" message and LLM-INSTALL.md reference
  ```

- [ ] ⬜ **Task 2.3**: Manual test — verify not-running case still shows restart guidance (flag not set):
  ```bash
  bash -c '
    source .claude/init.sh 2>/dev/null || true
    # _HOOKS_DAEMON_NOT_INSTALLED is false (default)
    emit_hook_error "SessionStart" "daemon_startup_failed" "test"
  ' | python3 -m json.tool
  # Expected: "Not currently running" with restart instructions (unchanged)
  ```

- [ ] ⬜ **Task 2.4**: Manual test — verify CI enforced case unchanged:
  ```bash
  bash -c '
    source .claude/init.sh 2>/dev/null || true
    _HOOKS_DAEMON_CI_ENFORCED=true
    emit_hook_error "PreToolUse" "daemon_startup_failed" "test"
  ' | python3 -m json.tool
  # Expected: deny decision with "STOP" message (unchanged)
  ```

### Phase 3: Full QA

- [ ] ⬜ **Task 3.1**: Run full QA suite
  ```bash
  ./scripts/qa/run_all.sh
  ```
  Expected: ALL CHECKS PASSED (especially shell check)

### Phase 4: Acceptance Test Coverage

- [ ] ⬜ **Task 4.1**: Check if the `init.sh` path is tested via `generate-playbook` — it's a shell script so won't appear in Python handler playbook. Document the manual verification steps from Phase 2 as the acceptance test record.

- [ ] ⬜ **Task 4.2**: Commit with clear message:
  ```
  Fix: fresh-clone shows install guidance instead of restart advice
  ```

## Message Design

### Not installed (new)
```
HOOKS DAEMON: Not installed

This project uses the Claude Code Hooks Daemon for safety enforcement,
but the daemon is not installed in this environment.

ALL safety handlers, code quality checks, and workflow enforcement are INACTIVE.

TO INSTALL — read and follow the guide (do not improvise):
  CLAUDE/LLM-INSTALL.md

After installing, the daemon starts automatically on the next hook event.
```

**PreToolUse**: fail-open advisory (hookSpecificOutput) — LLM must be able to run install commands
**Stop/SubagentStop**: block — don't let session end silently with safety inactive

### Not running (unchanged)
```
HOOKS DAEMON: Not currently running
...
TO FIX: Run: python -m claude_code_hooks_daemon.daemon.cli restart
```

### CI enforced (unchanged)
```
STOP - DO NOT PROCEED
...
```

## Success Criteria

- [ ] Fresh clone of a hooks-daemon project shows "Not installed" + LLM-INSTALL.md guidance
- [ ] "Installed but not running" case still shows "Not currently running" + restart advice
- [ ] CI passthrough and CI enforced behaviour unchanged
- [ ] `shellcheck` passes on modified `init.sh`
- [ ] Daemon restarts cleanly after change
- [ ] Full QA passes

## Files Changed

| File | Change |
|------|--------|
| `.claude/init.sh` | Add flag, helper fn, detection in ensure_daemon(), new message branch in emit_hook_error() |

No Python files, no config changes, no new handlers.

## Notes

### Why fail-open for PreToolUse (not-installed case)?

The LLM needs to be able to read `CLAUDE/LLM-INSTALL.md` and run install commands (curl, bash, git). Hard-blocking PreToolUse would make the daemon impossible to install via the LLM. The advisory approach (show warning, allow through) is correct.

### Why block Stop/SubagentStop?

Same reason as "not running" case: we don't want the session to end silently while safety handlers are inactive. Blocking Stop gives the LLM (and user) visibility that something needs to be addressed.

### Partial installs

If `.claude/hooks-daemon/` exists but the venv is missing (broken partial install), `_is_daemon_installed()` returns false → "not installed" message → guide to LLM-INSTALL.md. This is intentional — a broken install needs reinstallation, not a restart.
