# Plan 00039: Progressive Verbosity & Data Layer Handler Enhancements

**Status**: Complete (2026-02-09)
**Created**: 2026-02-09
**Owner**: Claude Opus 4.6
**Priority**: High

## Overview

Plan 00037 built the Daemon Data Layer (SessionState, HandlerHistory, TranscriptReader, DaemonDataLayer facade). This plan enhances existing handlers to USE it.

**Primary enhancement**: Progressive verbosity - blocking handlers escalate message detail based on how many times they've already blocked. Terse first (save tokens), verbose after repeated blocks (agent being dumb).

**Secondary**: Show block count in status line via DaemonStatsHandler.

## Goals

- Implement count_blocks_by_handler() method in HandlerHistory
- Add progressive verbosity to PipeBlockerHandler (3 tiers)
- Add progressive verbosity to SedBlockerHandler (3 tiers)
- Add progressive verbosity to DestructiveGitHandler (3 tiers)
- Display block count in DaemonStatsHandler status line
- Save tokens by being terse on first block, verbose only when needed

## Non-Goals

- Haiku enforcement (deferred to separate plan)
- Other data layer features beyond block counting

## Context & Background

After Plan 00037 created the data layer infrastructure, handlers needed to actually use it. The primary use case was progressive verbosity:

**Problem**: Blocking handlers currently show full verbose messages every time, wasting tokens when the agent gets the message on first try.

**Solution**: Track block history per handler, show terse message first, escalate to verbose only after repeated blocks.

## Tasks

### Phase 1: Foundation - count_blocks_by_handler() ✅

- [x] Add method to HandlerHistory
- [x] Implement: `count(handler_id, decision in [deny, ask])`
- [x] Write 6 comprehensive tests
- [x] Export from core/__init__.py

**Files**:
- `src/claude_code_hooks_daemon/core/handler_history.py`
- `tests/unit/core/test_handler_history.py`

### Phase 2: Progressive Verbosity - PipeBlockerHandler ✅

- [x] Refactor handle() to check block count
- [x] Implement 3 tiers: terse (0), standard (1-2), verbose (3+)
- [x] Add private methods: _terse_reason(), _standard_reason(), _verbose_reason()
- [x] Update tests to mock get_data_layer()
- [x] Test each verbosity tier

**Files**:
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py`
- `tests/unit/handlers/test_pipe_blocker.py`

### Phase 3: Progressive Verbosity - SedBlockerHandler ✅

- [x] Same pattern as PipeBlocker
- [x] Terse: "BLOCKED: sed is forbidden. Use Edit tool."
- [x] Standard: Add alternatives
- [x] Verbose: Full message with examples

**Files**:
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/sed_blocker.py`
- `tests/unit/handlers/test_sed_blocker.py`

### Phase 4: Progressive Verbosity - DestructiveGitHandler ✅

- [x] Same pattern
- [x] Terse: "{specific_reason}. Ask the user."
- [x] Standard: Add command line and safe alternatives
- [x] Verbose: Full warnings

**Files**:
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py`
- `tests/unit/handlers/test_destructive_git.py`

### Phase 5: DaemonStats Block Count ✅

- [x] Add block count display after error count
- [x] Format: "| 🛡️ {count} blocks"
- [x] Only show if count > 0
- [x] Mock get_data_layer() in tests

**Files**:
- `src/claude_code_hooks_daemon/handlers/status_line/daemon_stats.py`
- `tests/unit/handlers/status_line/test_daemon_stats.py`

## Technical Decisions

### Decision 1: Block count thresholds
**Context**: How many blocks before escalating verbosity?
**Decision**: 0 = terse, 1-2 = standard, 3+ = verbose
**Rationale**: One chance to be terse, two attempts with guidance, then assume agent needs full context
**Date**: 2026-02-09

### Decision 2: History records timing
**Context**: When are history records created?
**Decision**: After handler returns (in DaemonController)
**Rationale**: Current block doesn't count toward its own verbosity tier
**Date**: 2026-02-09

## Success Criteria

- [x] count_blocks_by_handler() implemented with full test coverage
- [x] PipeBlocker has 3 verbosity tiers
- [x] SedBlocker has 3 verbosity tiers
- [x] DestructiveGit has 3 verbosity tiers
- [x] DaemonStats shows block count when > 0
- [x] All tests pass (95%+ coverage maintained)
- [x] Layer 1 QA: All 7 checks pass
- [x] Layer 2 QA: All 3 gates pass (QA Agent, Senior Reviewer, Honesty Checker)
- [x] Layer 3 QA: 30/32 acceptance tests pass (93.75%)
- [x] Daemon restarts successfully

## Files Modified

| File | Status |
|------|--------|
| `src/claude_code_hooks_daemon/core/handler_history.py` | ✅ Complete |
| `src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py` | ✅ Complete |
| `src/claude_code_hooks_daemon/handlers/pre_tool_use/sed_blocker.py` | ✅ Complete |
| `src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py` | ✅ Complete |
| `src/claude_code_hooks_daemon/handlers/status_line/daemon_stats.py` | ✅ Complete |
| `tests/unit/core/test_handler_history.py` | ✅ Complete |
| `tests/unit/handlers/test_pipe_blocker.py` | ✅ Complete |
| `tests/unit/handlers/test_sed_blocker.py` | ✅ Complete |
| `tests/unit/handlers/test_destructive_git.py` | ✅ Complete |
| `tests/unit/handlers/status_line/test_daemon_stats.py` | ✅ Complete |

## Dependencies

- Depends on: Plan 00037 (Daemon Data Layer) - Complete
- Blocks: None

## Notes & Updates

### 2026-02-09
- All 5 phases implemented with TDD
- Full 3-layer QA completed
- Layer 1: All 7 automated checks pass
- Layer 2: All 3 sub-agent gates pass
- Layer 3: 30/32 acceptance tests pass (one false positive, one plugin manual test)
- Discovered bug: PlaybookGenerator missing plugins (Plan 00040 created)
- Work complete and verified
