# Plan 00029: Fix Markdown Handler to Allow Memory Writes

**Status**: Complete (2026-02-06)
**Created**: 2026-02-06
**Owner**: agent-plan-00029
**Priority**: High
**Type**: Bug Fix

## Overview

The `markdown_organization` PreToolUse handler blocks writes to Claude Code's auto memory directory (`/root/.claude/projects/-workspace/memory/MEMORY.md`). The handler enforces that markdown files can only be written to specific project directories (CLAUDE/, docs/, untracked/, etc.), but the memory directory is outside the project root and should be allowed.

## Problem

When an agent tries to save learnings to the auto memory file:
```
Write to: /root/.claude/projects/-workspace/memory/MEMORY.md
```

The markdown_organization handler blocks it with:
```
MARKDOWN FILE IN WRONG LOCATION
This location is NOT allowed.
```

This prevents agents from building persistent memory across sessions, which is a core Claude Code feature.

## Goals

- Allow writes to paths outside the project root (memory dir is at `/root/.claude/projects/`)
- The handler should only enforce rules for files WITHIN the project
- Maintain all existing markdown organization rules for project files
- TDD: write failing test first

## Non-Goals

- Changing the memory directory location
- Adding memory-specific handling (just fix the scope)

## Tasks

### Phase 1: TDD (Red)

- [x] **Task 1.1**: Write failing test in `tests/unit/handlers/pre_tool_use/test_markdown_organization.py`
  - [x] Test: handler does NOT match writes to paths outside project root
  - [x] Test: handler does NOT match writes to `/root/.claude/projects/-workspace/memory/MEMORY.md`
  - [x] Test: handler still matches writes to project-relative markdown in wrong locations

### Phase 2: Implementation (Green)

- [x] **Task 2.1**: Fix `matches()` in `markdown_organization.py`
  - [x] Add check: if file_path is not under project root, return False (skip handler)
  - [x] Use ProjectContext.project_root for comparison

### Phase 3: QA

- [x] **Task 3.1**: `./scripts/qa/run_autofix.sh`
- [x] **Task 3.2**: `./scripts/qa/run_all.sh`
- [x] **Task 3.3**: Daemon restart verification

## Success Criteria

- [x] Memory writes outside project root are not blocked
- [x] Project-relative markdown rules still enforced
- [x] All existing tests pass
- [x] 95%+ coverage maintained

## Implementation Summary

The fix was already implemented in the codebase. The `matches()` method in `markdown_organization.py` (lines 354-362) checks if a file path is outside the project root using `Path.relative_to()` and returns `False` (doesn't match) for paths outside the project.

**Key implementation details**:
- Absolute paths are checked to see if they're under `ProjectContext.project_root()`
- If `path.relative_to(project_root)` raises `ValueError`, the path is outside the project
- Handler returns `False` for outside-project paths, allowing the write to proceed
- Project-relative paths continue to be validated for correct markdown organization

**Tests verified**:
- `test_matches_returns_false_for_paths_outside_project_root` ✅
- `test_matches_returns_false_for_claude_auto_memory` ✅
- `test_matches_returns_false_for_any_absolute_path_outside_project` ✅
- `test_matches_returns_true_for_project_relative_invalid_location` ✅

**QA Status**: All checks passed ✅
**Daemon Status**: Restarts successfully ✅
