# Plan 00120: Git Hooks Executable Fixer Handler

**Status**: Complete
**Type**: Handler Implementation
**Event Type**: PostToolUse
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded
**Created**: 2026-06-09

## Overview

When git runs a command (e.g. `git push`) and finds a hook file under the
repository's hooks directory that lacks the execute permission bit, it silently
skips that hook and prints a hint to stderr:

```
hint: The '.git/hooks/pre-push' hook was ignored because it's not set as executable.
```

This is dangerous: a project's safety/quality git hooks (pre-push, pre-commit,
etc.) become silently inert. The user wants the daemon to detect this warning in
git command output and **automatically remediate** it by ensuring all git hook
files are executable.

## Goals

- Detect the "not set as executable" hint in Bash (git) command output.
- Locate the repository's real hooks directory robustly (worktree/submodule
  safe) via `git rev-parse --git-path hooks`.
- Make every non-`.sample` hook file executable using least-privilege bits
  (add execute only where read is already granted).
- Report which hooks were fixed via advisory context so the action is visible.
- Maintain 95%+ coverage; zero QA failures; daemon restarts cleanly.

## Non-Goals

- Does NOT touch `.sample` files (git ignores them by design).
- Does NOT modify hooks that are already executable.
- Does NOT block any command (purely advisory / side-effecting remediation).
- Does NOT alter git config (`core.hooksPath` is honoured automatically because
  we resolve the active hooks dir from git itself).

## Context & Background

- Existing pattern: `bash_error_detector` (PostToolUse) parses `tool_response`
  `stdout`/`stderr`. We reuse that field-access pattern.
- Existing pattern: `lint_on_edit` runs trusted subprocesses with list args and
  degrades gracefully on `FileNotFoundError`/`TimeoutExpired`. We mirror that.
- Remediation uses `os.chmod`, NOT a `chmod` Bash command, so it does not
  interact with the `dangerous_permissions` blocker and is least-privilege.

## Tasks

### Phase 1: TDD Implementation

- [x] Create test file `tests/unit/handlers/post_tool_use/test_git_hooks_executable_fixer.py`
- [x] RED: init tests (handler_id, priority, terminal=False, tags)
- [x] RED: `matches()` positive (warning in stderr) / negative (no warning, non-Bash)
- [x] RED: `handle()` makes a non-executable real hook executable, leaves `.sample` alone
- [x] RED: `handle()` reports fixed hooks in context; already-executable → no change
- [x] RED: `handle()` degrades gracefully when `git rev-parse` unavailable
- [x] GREEN: implement `GitHooksExecutableFixerHandler`
- [x] REFACTOR: extract constants, split subprocess (handle) from pure parse helper

### Phase 2: Registration & Integration

- [x] Add `HandlerID.GIT_HOOKS_EXECUTABLE_FIXER` (constants/handlers.py)
- [x] Add `Priority.GIT_HOOKS_EXECUTABLE_FIXER` (constants/priority.py)
- [x] Export from `handlers/post_tool_use/__init__.py`
- [x] Register in `hooks/post_tool_use.py` builtin map
- [x] Add default to `daemon/init_config.py` and `.claude/hooks-daemon.yaml.example`
- [x] Enable in project `.claude/hooks-daemon.yaml`

### Phase 3: Verification

- [x] `get_claude_md()` guidance returned (it is a side-effecting handler)
- [x] `get_acceptance_tests()` defined
- [x] Run full QA: `./scripts/qa/llm_qa.py all` → 13/13 PASSED
- [x] Restart daemon, verify RUNNING
- [x] Live verify: created a 644 pre-push hook, fed the git hint through the live
  daemon socket, confirmed it became 755 and `.sample` stayed 644

## Handler Specification

```python
class GitHooksExecutableFixerHandler(Handler):
    # PostToolUse, Bash only, terminal=False
    # matches: warning signature present in stdout/stderr
    # handle: resolve hooks dir via git rev-parse --git-path hooks,
    #         os.chmod each non-.sample, non-executable file to add exec bits
    #         (mode | ((mode & 0o444) >> 2)), report fixed files as context
```

## Success Criteria

- [x] Handler auto-fixes non-executable git hooks on detecting the git hint
- [x] `.sample` files and already-executable hooks untouched
- [x] 95%+ coverage maintained (handler file: 100%)
- [x] All QA checks pass (13/13)
- [x] Daemon restarts successfully; live test confirms remediation

## Notes & Updates

### 2026-06-09

- Plan created. Triggered by a real `git push` surfacing the pre-push
  "not set as executable" hint during dogfooding.
- Complete. Delivered in the Plan 00120 commit (git is the source of truth for
  the hash). Added `GitHooksExecutableFixerHandler` (PostToolUse, priority 27,
  non-terminal): on detecting git's "not set as executable" hint it resolves the
  active hooks dir via `git rev-parse --git-path hooks` and `os.chmod`s every
  non-`.sample`, non-executable hook with least-privilege exec bits. 23 unit
  tests, 100% file coverage, full QA 13/13, live socket test verified.
