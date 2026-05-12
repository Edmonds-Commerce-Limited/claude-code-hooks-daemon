# Plan 00089: Fix auto_approve_reads Schema Mismatch + AskUserQuestion YOLO Bypass

**Status**: Complete
**Owner**: Claude
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded
**Delivered in**: commit `eb74e4a` (Phases 1 + 2); closed out as part of Plan 00107 Wave 1

## Overview

Two bugs reported in `untracked/hooks-daemon-askuserquestion-tool-incorrect-bypass.md`:

1. **Bug 2 (auto_approve_reads dead code)**: The `auto_approve_reads` PermissionRequest handler checks `permission_type` field, but real PermissionRequest events use `permission_suggestions` array. The handler's `matches()` always returns False — it never fires. The schema validation tests already document this as a known bug.

2. **Bug 1 (AskUserQuestion empty in YOLO mode)**: In YOLO mode (`--dangerously-skip-permissions`), `AskUserQuestion` tool calls are auto-dismissed with empty answers. The daemon can compensate by creating a PreToolUse handler that blocks AskUserQuestion when running in a non-interactive permission mode, preventing the wasted round-trip.

## Goals

- Fix `auto_approve_reads` handler to use real PermissionRequest event structure (`tool_name` field)
- Add `PERMISSION_SUGGESTIONS` to `HookInputField` constants (replace misleading `PERMISSION_TYPE`)
- Create PreToolUse handler to block AskUserQuestion in YOLO/non-interactive mode
- All changes follow TDD with 95%+ coverage
- All QA checks pass, daemon restarts successfully

## Non-Goals

- Fixing Claude Code's YOLO mode behaviour itself (upstream issue)
- Capturing real PermissionRequest events (YOLO mode never fires them)
- Changing schema validation logic

## Tasks

### Phase 1: Bug 2 — Fix auto_approve_reads (TDD)

- [x] **Task 1.1**: Update tests to use real event structure (RED)
  - [x] Change test hook_input to use `tool_name` instead of `permission_type`
  - [x] Add `permission_suggestions` array to test fixtures
  - [x] Tests should FAIL against current handler code
- [x] **Task 1.2**: Fix handler implementation (GREEN)
  - [x] Rewrite `matches()` to check `tool_name` against read-only tools
  - [x] Rewrite `handle()` to approve read tools, deny write tools
  - [x] Use `ToolName` constants for tool name matching
- [x] **Task 1.3**: Update constants (REFACTOR)
  - [x] Add `PERMISSION_SUGGESTIONS` to `HookInputField`
  - [x] Mark `PERMISSION_TYPE` with deprecation comment
- [x] **Task 1.4**: Verify
  - [x] Run unit tests for handler
  - [x] Run QA suite
  - [x] Restart daemon

### Phase 2: Bug 1 — AskUserQuestion YOLO bypass handler (TDD)

- [x] **Task 2.1**: Add HandlerID and Priority constants for new handler
- [x] **Task 2.2**: Write failing tests (RED)
  - [x] Test matches() positive: AskUserQuestion + non-interactive permission_mode
  - [x] Test matches() negative: AskUserQuestion + default mode
  - [x] Test matches() negative: other tools in YOLO mode
  - [x] Test handle() returns deny with helpful message
- [x] **Task 2.3**: Implement handler (GREEN)
  - [x] PreToolUse handler matching tool_name == AskUserQuestion
  - [x] Check permission_mode for non-interactive modes
  - [x] Return deny with guidance to use inline text
- [x] **Task 2.4**: Register handler in config and verify
  - [x] Add to hooks-daemon.yaml
  - [x] Run QA suite
  - [x] Restart daemon

### Phase 3: Commit

- [x] **Task 3.1**: Run full QA suite
- [x] **Task 3.2**: Checkpoint commit

## Success Criteria

- [x] `auto_approve_reads` handler matches real PermissionRequest event structure
- [x] AskUserQuestion is blocked in YOLO mode with helpful guidance
- [x] All QA checks pass
- [x] Daemon restarts successfully
- [x] 95%+ test coverage maintained
