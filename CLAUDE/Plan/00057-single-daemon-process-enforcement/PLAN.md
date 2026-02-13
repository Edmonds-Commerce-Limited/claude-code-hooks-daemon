# Plan 00057: Single Daemon Process Enforcement

**Status**: Not Started
**Created**: 2026-02-13
**Owner**: Claude Sonnet 4.5
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Implement a robust single daemon process enforcement system that prevents multiple daemon instances from running simultaneously. This is particularly valuable in container environments where it's safe to aggressively ensure only one daemon process exists.

The system will include:
- Container detection during install/upgrade
- Configurable single-process enforcement
- Robust process verification (not just PID file checking)
- Safe process cleanup when multiple daemons detected

## Goals

- Add `enforce_single_daemon_process` config option to DaemonConfig
- Implement robust daemon process detection and verification
- Create container detection utility for install/upgrade phase
- Auto-enable enforcement in container environments
- Ensure zero false positives (don't kill unrelated processes)
- Maintain backward compatibility (feature is opt-in by default)

## Non-Goals

- Not implementing cross-machine daemon coordination (only local process management)
- Not implementing daemon clustering or load balancing
- Not changing existing daemon lifecycle for non-enforced mode

## Execution Strategy

**Recommended approach**: Sub-Agent Orchestration (Sonnet main thread)

### Phase-Level Parallelization

**Independent phases** that can be executed in parallel:
- Phase 2 (Container Detection) - python-developer agent
- Phase 3 (Process Verification) - python-developer agent

**Sequential phases** that must complete before others:
1. Phase 1 (Design & Config) - main thread (architectural decisions)
2. Phase 2 & 3 in parallel - delegated to sub-agents
3. Phase 4 (Enforcement Logic) - main thread (integrates Phase 2 & 3)
4. Phase 5 (Install Integration) - python-developer agent
5. Phase 6 (Integration Testing) - qa-runner agent
6. Phase 7 (Documentation) - main thread
7. Phase 8 (Acceptance Testing) - main thread (real tool calls required)

### Sub-Agent Delegation

**Parallel execution** (after Phase 1):
```
Main (Sonnet) spawns:
├─ Agent A: Phase 2 (Container Detection utility + tests)
└─ Agent B: Phase 3 (Process Verification logic + tests)

Main waits for both, then proceeds to Phase 4
```

**Benefits**:
- Reduces total execution time (~40% faster with parallelization)
- Agents work independently on isolated modules
- Main thread focuses on coordination and integration

## Context & Background

### Current State

The daemon start process (`cmd_start()` in `cli.py`) currently:
1. Reads PID file via `read_pid_file()`
2. If PID exists, assumes daemon is running and exits
3. No verification that process is actually running
4. No verification that it's actually our daemon (PID could be reused)

**Problems**:
- Stale PID files cause false "already running" messages
- Multiple daemon processes could exist if PID files are in different locations
- No protection against accidental multiple starts

### Container Safety

In containerized environments (Docker, Podman):
- Only one project per container (isolated workspace)
- Safe to aggressively enforce single daemon
- Root access available for process management
- No risk of killing daemons from other projects

Existing container detection: `handlers/session_start/yolo_container_detection.py` has robust multi-indicator detection system.

## Tasks

### Phase 1: Design & Configuration

- [ ] ⬜ **Design process verification algorithm**
  - [ ] ⬜ Define what makes a process "our daemon"
  - [ ] ⬜ Design PID validation strategy (process exists, correct command, correct project)
  - [ ] ⬜ Design cleanup strategy (when is it safe to kill?)
  - [ ] ⬜ Document edge cases and error handling

- [ ] ⬜ **Add config option to DaemonConfig**
  - [ ] ⬜ Add `enforce_single_daemon_process: bool` field (default False)
  - [ ] ⬜ Update config schema and examples
  - [ ] ⬜ Write tests for config loading with new field
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

### Phase 2: Container Detection Utility

- [ ] ⬜ **Extract container detection logic**
  - [ ] ⬜ Create `utils/container_detection.py` module
  - [ ] ⬜ Extract scoring logic from `yolo_container_detection.py`
  - [ ] ⬜ Create `is_container_environment()` function (returns bool)
  - [ ] ⬜ Create `get_container_indicators()` function (for debugging)

- [ ] ⬜ **TDD: Write container detection tests**
  - [ ] ⬜ Create `tests/unit/utils/test_container_detection.py`
  - [ ] ⬜ Write failing tests for YOLO container detection
  - [ ] ⬜ Write failing tests for Docker/Podman detection
  - [ ] ⬜ Write failing tests for devcontainer detection
  - [ ] ⬜ Write failing tests for false negatives (normal Linux/macOS)

- [ ] ⬜ **Implement container detection utility**
  - [ ] ⬜ Implement `is_container_environment()` with confidence scoring
  - [ ] ⬜ Make tests pass
  - [ ] ⬜ Refactor for clarity
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

### Phase 3: Process Verification Logic

- [ ] ⬜ **TDD: Write process verification tests**
  - [ ] ⬜ Create `tests/unit/daemon/test_process_verification.py`
  - [ ] ⬜ Write failing test: PID exists and process running
  - [ ] ⬜ Write failing test: PID exists but process dead (stale)
  - [ ] ⬜ Write failing test: PID exists but different process
  - [ ] ⬜ Write failing test: No PID file
  - [ ] ⬜ Write failing test: Multiple daemon processes detected

- [ ] ⬜ **Implement process verification**
  - [ ] ⬜ Create `daemon/process_verification.py` module
  - [ ] ⬜ Implement `is_daemon_running(pid: int, project_path: Path) -> bool`
  - [ ] ⬜ Implement `find_all_daemon_processes(project_path: Path) -> list[int]`
  - [ ] ⬜ Implement `verify_daemon_process(pid: int) -> bool`
  - [ ] ⬜ Make tests pass
  - [ ] ⬜ Refactor for clarity
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

### Phase 4: Enforcement Logic

- [ ] ⬜ **TDD: Write enforcement tests**
  - [ ] ⬜ Create `tests/unit/daemon/test_enforcement.py`
  - [ ] ⬜ Write failing test: Single healthy daemon (no action)
  - [ ] ⬜ Write failing test: Multiple daemons (cleanup triggered)
  - [ ] ⬜ Write failing test: Stale PID file (cleanup triggered)
  - [ ] ⬜ Write failing test: Enforcement disabled (no cleanup)
  - [ ] ⬜ Write failing test: Non-container env (safer enforcement)

- [ ] ⬜ **Implement enforcement in cmd_start()**
  - [ ] ⬜ Check `enforce_single_daemon_process` config
  - [ ] ⬜ If enabled, call verification logic
  - [ ] ⬜ If multiple processes found, attempt cleanup
  - [ ] ⬜ Log all enforcement actions
  - [ ] ⬜ Make tests pass
  - [ ] ⬜ Refactor for clarity
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

### Phase 5: Install/Upgrade Integration

- [ ] ⬜ **Update installer to detect containers**
  - [ ] ⬜ Add container detection to `daemon/init_config.py`
  - [ ] ⬜ If container detected, set `enforce_single_daemon_process: true`
  - [ ] ⬜ Otherwise, leave commented with explanation
  - [ ] ⬜ Update config template generation

- [ ] ⬜ **Update configuration examples**
  - [ ] ⬜ Update `.claude/hooks-daemon.yaml.example`
  - [ ] ⬜ Add comments explaining when to enable
  - [ ] ⬜ Document container auto-detection behavior

### Phase 6: Integration Testing

- [ ] ⬜ **Integration tests**
  - [ ] ⬜ Test enforcement with real daemon lifecycle
  - [ ] ⬜ Test multiple start attempts with enforcement enabled
  - [ ] ⬜ Test stale PID file cleanup
  - [ ] ⬜ Test enforcement disabled (backward compatibility)
  - [ ] ⬜ Run full test suite: `pytest tests/ -v`
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`

- [ ] ⬜ **Daemon load verification (MANDATORY)**
  - [ ] ⬜ Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] ⬜ Verify status: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`
  - [ ] ⬜ Check logs: `$PYTHON -m claude_code_hooks_daemon.daemon.cli logs | grep -i error`
  - [ ] ⬜ Expected: No errors, daemon RUNNING

### Phase 7: Documentation

- [ ] ⬜ **Update documentation**
  - [ ] ⬜ Update CLAUDE.md with new config option
  - [ ] ⬜ Document enforcement behavior in ARCHITECTURE.md
  - [ ] ⬜ Add troubleshooting section for enforcement issues
  - [ ] ⬜ Update LLM-INSTALL.md with container auto-detection

### Phase 8: Acceptance Testing

- [ ] ⬜ **Live testing scenarios**
  - [ ] ⬜ Test in YOLO container with enforcement enabled
  - [ ] ⬜ Test multiple start attempts (should succeed without duplicates)
  - [ ] ⬜ Test with stale PID file (should clean up and start)
  - [ ] ⬜ Test in non-container env with enforcement disabled
  - [ ] ⬜ Verify no false positives (don't kill wrong processes)

## Technical Decisions

### Decision 1: Process Verification Strategy
**Context**: Need to verify a PID actually belongs to our daemon, not a reused PID.

**Options Considered**:
1. Check PID only (current behavior) - Fast but unreliable
2. Check PID + process name - Reliable but could match other Python processes
3. Check PID + process name + command-line args - Most reliable, some overhead
4. Check PID + socket connection test - Most reliable but expensive

**Decision**: Use option 3 (PID + process name + command-line args)
- Checks process exists (`os.kill(pid, 0)` or `/proc/{pid}`)
- Checks process command contains "claude_code_hooks_daemon"
- Checks process was started from correct project path
- Fast enough for startup check (<10ms)
- Reliable across platforms (psutil or /proc on Linux, ps on macOS)

**Date**: 2026-02-13

### Decision 2: Cleanup Strategy
**Context**: When should we kill existing daemon processes?

**Options Considered**:
1. Always kill all daemons - Too aggressive, could kill valid daemons
2. Never kill, just warn - Too passive, doesn't solve the problem
3. Kill only if in container - Safe but limits feature usefulness
4. Kill if config enabled AND (in container OR stale PID) - Balanced approach

**Decision**: Use option 4 (conditional aggressive cleanup)
- In containers: Kill all daemon processes for this project
- Outside containers: Only clean up stale PID files
- Requires `enforce_single_daemon_process: true` in config
- Log all cleanup actions for debugging

**Date**: 2026-02-13

### Decision 3: Container Detection Threshold
**Context**: When to auto-enable enforcement during install?

**Options Considered**:
1. Enable if ANY container indicator present - Too aggressive
2. Enable if confidence score >= 3 (same as YOLO handler) - Balanced
3. Enable only for CLAUDECODE=1 - Too conservative
4. Never auto-enable, require manual config - Too passive

**Decision**: Use option 2 (confidence score >= 3)
- Reuses proven detection logic from `yolo_container_detection.py`
- Low false positive rate (requires multiple indicators)
- User can override by commenting out config option
- Provides safety where it matters most (containers)

**Date**: 2026-02-13

## Success Criteria

- [ ] Config option `enforce_single_daemon_process` added to DaemonConfig
- [ ] Container detection utility implemented and tested
- [ ] Process verification logic catches stale PID files
- [ ] Multiple daemon processes detected and cleaned up when enforcement enabled
- [ ] No false positives (never kills unrelated processes)
- [ ] Installer auto-enables enforcement in containers
- [ ] All tests passing with 95%+ coverage
- [ ] All QA checks pass: `./scripts/qa/run_all.sh`
- [ ] Daemon loads successfully after changes
- [ ] Documentation updated
- [ ] Live testing confirms enforcement works in containers

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Kill wrong process (PID reuse) | High | Low | Use command-line verification, not just PID |
| False positive in non-container | Medium | Low | Conservative container detection (score >= 3) |
| Process verification too slow | Low | Medium | Use lightweight checks (psutil or /proc) |
| Cross-platform compatibility | Medium | Medium | Test on Linux and macOS, use psutil for portability |
| Stale PID file not detected | Medium | Low | Verify process is running, not just PID file exists |

## Dependencies

- Depends on: None (self-contained feature)
- Blocks: None
- Related: Plan 00033 (Status Line Enhancements) - uses same YOLO detection

## Notes & Updates

### 2026-02-13
- Plan created based on user request
- Feature is opt-in by default (backward compatible)
- Container auto-detection ensures safe defaults
- Enforcement logic is conservative outside containers
