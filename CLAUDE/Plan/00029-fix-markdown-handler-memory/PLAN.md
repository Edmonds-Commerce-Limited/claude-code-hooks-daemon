# Plan 00029: Fix Markdown Handler to Allow Memory Writes

**Status**: Not Started
**Created**: 2026-02-06
**Owner**: To be assigned
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

- [ ] **Task 1.1**: Write failing test in `tests/unit/handlers/pre_tool_use/test_markdown_organization.py`
  - [ ] Test: handler does NOT match writes to paths outside project root
  - [ ] Test: handler does NOT match writes to `/root/.claude/projects/-workspace/memory/MEMORY.md`
  - [ ] Test: handler still matches writes to project-relative markdown in wrong locations

### Phase 2: Implementation (Green)

- [ ] **Task 2.1**: Fix `matches()` in `markdown_organization.py`
  - [ ] Add check: if file_path is not under project root, return False (skip handler)
  - [ ] Use ProjectContext.project_root for comparison

### Phase 3: QA

- [ ] **Task 3.1**: `./scripts/qa/run_autofix.sh`
- [ ] **Task 3.2**: `./scripts/qa/run_all.sh`
- [ ] **Task 3.3**: Daemon restart verification

## Success Criteria

- [ ] Memory writes outside project root are not blocked
- [ ] Project-relative markdown rules still enforced
- [ ] All existing tests pass
- [ ] 95%+ coverage maintained
