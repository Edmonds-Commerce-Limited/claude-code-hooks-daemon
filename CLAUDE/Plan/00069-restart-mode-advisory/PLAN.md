# Plan 00069: Restart Mode Preservation Advisory

**Status**: In Progress
**Created**: 2026-02-24
**Owner**: Claude
**Priority**: Medium
**Recommended Executor**: Sonnet

## Overview

Daemon mode (e.g. `unattended`) is runtime state held in-memory by `ModeManager`. When the daemon restarts, mode resets to `default_mode` from config (usually `default`). An agent that set `unattended` mode before a restart has no way to know the mode was lost — they silently lose stop-blocking protection.

The fix: make `cmd_restart` query the current mode before stopping, then after a successful start, print a clear advisory showing what mode was active and the exact command to restore it.

## Goals

- Preserve mode awareness across daemon restarts
- Print actionable advisory with restore command when non-default mode is lost
- No output for the common case (default mode)

## Non-Goals

- Automatic mode restoration (too risky — mode might have been set for a specific context)
- Persisting mode to disk

## Tasks

### Phase 1: TDD - Write Failing Tests

- [ ] Add `_get_current_mode` helper tests to `test_cli_modes.py`
- [ ] Add `_print_mode_advisory` helper tests to `test_cli_modes.py`
- [ ] Add `cmd_restart` integration test for mode advisory

### Phase 2: Implementation

- [ ] Add `_get_current_mode` helper to `cli.py`
- [ ] Add `_print_mode_advisory` helper to `cli.py`
- [ ] Modify `cmd_restart` to use both helpers

### Phase 3: Verification

- [ ] All tests pass
- [ ] Full QA passes
- [ ] Daemon restart verification
- [ ] Manual test with set-mode + restart

## Critical Files

| File | Action |
|------|--------|
| `src/claude_code_hooks_daemon/daemon/cli.py` | Modify `cmd_restart`, add 2 helpers |
| `tests/unit/daemon/test_cli_modes.py` | Add tests for new helpers + restart integration |

## Success Criteria

- [ ] `_get_current_mode` returns mode dict when daemon running, None when not
- [ ] `_print_mode_advisory` prints restore command for non-default mode, nothing for default
- [ ] `cmd_restart` captures mode before stop, prints advisory after start
- [ ] All QA checks pass
- [ ] Daemon loads successfully
