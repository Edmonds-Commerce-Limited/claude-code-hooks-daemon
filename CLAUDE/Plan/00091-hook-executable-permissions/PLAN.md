# Plan: Fix Hook Script Executable Permissions

**Status**: Not Started
**Created**: 2026-03-16
**Priority**: High
**Recommended Executor**: Sonnet

## Context

When users install the hooks daemon, hook scripts (`.claude/hooks/pre-tool-use`, etc.) are deployed with `chmod +x`. However, if the user's git repo has `core.fileMode=false`, git doesn't track the executable bit. After any merge/checkout/rebase, scripts revert to `100644` (non-executable) and hooks silently break.

The fix has three parts:
1. Force-commit hook scripts as `100755` via `git update-index --chmod=+x` during install/upgrade
2. Warn loudly on SessionStart if `core.fileMode=false` is detected
3. Existing deployments get fixed automatically via the upgrade path (which calls the same deploy function)

## Phase 1: Shell Script - `git_force_executable()` in `hooks_deploy.sh`

**File**: `scripts/install/hooks_deploy.sh`

- [ ] **Task 1.1**: Add `git_force_executable()` function after `set_hook_permissions()` (after line 198)
  - Check we're in a git repo (`git rev-parse --is-inside-work-tree`)
  - Find all hook scripts in `.claude/hooks/` (maxdepth 1, regular files)
  - For each: use `git ls-files --full-name` to get tracked path, then `git update-index --chmod=+x`
  - Also force-executable on `.claude/init.sh`
  - Warn if `core.fileMode=false` detected
  - All errors non-fatal (`|| true`)

- [ ] **Task 1.2**: Call `git_force_executable()` from `deploy_all_hooks()` (line ~243)
  - Place OUTSIDE the `if [ "$install_mode" != "self-install" ]` guard (both modes benefit)
  - Call after `set_hook_permissions()`

- [ ] **Task 1.3**: Verify shellcheck passes on modified file

## Phase 2: SessionStart Handler - `git_filemode_checker` (TDD)

### Constants

- [ ] **Task 2.1**: Add `HandlerID.GIT_FILEMODE_CHECKER` to `src/claude_code_hooks_daemon/constants/handlers.py` (after line 417)
  - `HandlerIDMeta(class_name="GitFilemodeCheckerHandler", config_key="git_filemode_checker", display_name="git-filemode-checker")`
  - Add `"git_filemode_checker"` to `HandlerKey` Literal (after `"optimal_config_checker"` ~line 512)

- [ ] **Task 2.2**: Add `GIT_FILEMODE_CHECKER = 53` to `src/claude_code_hooks_daemon/constants/priority.py` (after `OPTIMAL_CONFIG_CHECKER = 52`)

### RED: Write Failing Tests

- [ ] **Task 2.3**: Create `tests/unit/handlers/session_start/test_git_filemode_checker.py`
  - `TestInit`: handler_id, priority=53, terminal=False, tags (ADVISORY, GIT, NON_TERMINAL, ENVIRONMENT)
  - `TestMatches`: new session=True, resume session=False
  - `TestHandle`: filemode=false warns with "core.fileMode" + recommendation; filemode=true no warning; not git repo handled gracefully; subprocess timeout handled
  - `TestAcceptanceTests`: has at least 1 test

### GREEN: Implement Handler

- [ ] **Task 2.4**: Create `src/claude_code_hooks_daemon/handlers/session_start/git_filemode_checker.py`
  - Follow `optimal_config_checker.py` pattern exactly
  - `_is_resume_session()` - same logic (transcript size > 100 bytes)
  - `_get_filemode_setting()` - runs `git config --local core.fileMode`, returns "true"/"false"/None
  - `matches()` - only new sessions
  - `handle()` - warns loudly when filemode=false, recommends `git config core.fileMode true`
  - `get_acceptance_tests()` - CONTEXT type, SessionStart event, requires_main_thread=True
  - Use `subprocess.run` with `Timeout.VERSION_CHECK` (5 seconds), `nosec B603 B607` comments
  - Use constants: `HandlerID.GIT_FILEMODE_CHECKER`, `Priority.GIT_FILEMODE_CHECKER`, `HandlerTag.{ADVISORY,GIT,NON_TERMINAL,ENVIRONMENT}`

- [ ] **Task 2.5**: Register in `src/claude_code_hooks_daemon/handlers/session_start/__init__.py`
  - Add import and `__all__` entry

### Config

- [ ] **Task 2.6**: Register in `.claude/hooks-daemon.yaml` under `session_start:` (after `optimal_config_checker`, before `suggest_status_line`)
  ```yaml
  git_filemode_checker:
    enabled: true
    priority: 53
  ```

## Phase 3: Integration and Verification

- [ ] **Task 3.1**: Run tests, verify all pass with 95%+ coverage
- [ ] **Task 3.2**: Run `./scripts/qa/run_all.sh` - all 8 checks must pass
- [ ] **Task 3.3**: Run `shellcheck scripts/install/hooks_deploy.sh`
- [ ] **Task 3.4**: Restart daemon and verify RUNNING
- [ ] **Task 3.5**: Regenerate docs: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs`
- [ ] **Task 3.6**: Update `docs/guides/HANDLER_REFERENCE.md` with new handler entry
- [ ] **Task 3.7**: Commit checkpoint

## Key Files

| File | Action |
|------|--------|
| `scripts/install/hooks_deploy.sh` | Modify - add `git_force_executable()` |
| `src/.../constants/handlers.py` | Modify - add HandlerID + HandlerKey |
| `src/.../constants/priority.py` | Modify - add priority 53 |
| `src/.../handlers/session_start/git_filemode_checker.py` | **New** |
| `tests/unit/handlers/session_start/test_git_filemode_checker.py` | **New** |
| `src/.../handlers/session_start/__init__.py` | Modify - register import |
| `.claude/hooks-daemon.yaml` | Modify - register handler |
| `docs/guides/HANDLER_REFERENCE.md` | Modify - document handler |
| `.claude/HOOKS-DAEMON.md` | Regenerate |

## Verification

1. Unit tests pass with 95%+ coverage on new handler
2. All 8 QA checks pass
3. Shellcheck passes on modified shell script
4. Daemon restarts successfully with new handler loaded
5. `git ls-files -s .claude/hooks/pre-tool-use` shows `100755` after running deploy
