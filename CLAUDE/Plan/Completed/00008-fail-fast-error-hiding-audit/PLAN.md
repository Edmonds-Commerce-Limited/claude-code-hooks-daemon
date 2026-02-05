# Execution Plan: Fix All Error Hiding Violations

**Plan ID:** 00008-fail-fast-error-hiding-audit
**Status:** Ready for execution
**Priority:** CRITICAL
**Estimated scope:** 22 violations across 11 files

---

## Objectives

1. **Eliminate all silent failures** - Replace `except Exception: pass` with logging
2. **Use specific exception types** - Replace broad `Exception` with specific types
3. **Surface errors to users** - Ensure critical failures are visible
4. **Maintain test coverage** - Keep 95%+ coverage throughout fixes
5. **Validate with QA** - Run full QA suite after each file

---

## Success Criteria

- ✓ All 22 critical violations fixed
- ✓ All exceptions logged with appropriate level (debug/warning/error)
- ✓ Specific exception types used (no bare `except Exception`)
- ✓ QA passes (format, lint, type check, tests, coverage 95%+)
- ✓ Daemon restarts successfully
- ✓ Integration test validates error visibility

---

## Phased Approach

### Phase 1: Core Infrastructure (daemon/)
Fix daemon core files first as they impact all handlers.

**Files:**
1. daemon/paths.py (4 violations)
2. daemon/memory_log_handler.py (1 violation)
3. daemon/validation.py (1 violation)

**Estimated impact:** High - affects all handler error propagation

---

### Phase 2: Critical Handlers (workflow state)
Fix workflow state management - data loss risk.

**Files:**
4. handlers/pre_compact/workflow_state_pre_compact.py (6 violations)
5. handlers/session_start/workflow_state_restoration.py (1 violation)

**Estimated impact:** Critical - prevents data loss

---

### Phase 3: Safety Handlers (container detection)
Fix YOLO detection - security implications.

**Files:**
6. handlers/session_start/yolo_container_detection.py (4 violations)

**Estimated impact:** High - security handler must not fail silently

---

### Phase 4: User-Facing Handlers (status line, reminders)
Fix user-visible functionality.

**Files:**
7. handlers/status_line/daemon_stats.py (1 violation)
8. handlers/status_line/git_branch.py (1 violation)
9. handlers/stop/auto_continue_stop.py (1 violation)
10. handlers/subagent_stop/remind_validator.py (1 violation)

**Estimated impact:** Medium - affects user experience

---

### Phase 5: Configuration (config/)
Fix config loading and validation.

**Files:**
11. config/validator.py (1 violation)

**Estimated impact:** Medium - improves handler discovery errors

---

## Detailed Fix Plan

### Phase 1.1: daemon/paths.py (4 violations)

**File:** src/claude_code_hooks_daemon/daemon/paths.py

#### Violation #1 (lines 126-127): is_pid_alive() broad exception

**Current code:**
```python
except PermissionError:
    return True
except Exception:
    return False
```

**Fix:**
```python
except PermissionError:
    return True
except (ProcessLookupError, OSError) as e:
    logger.debug("PID check failed: %s", e)
    return False
```

**Test:** Add test case for OSError in is_pid_alive()

---

#### Violation #2 (line 152): read_pid_file() triple exception

**Current code:**
```python
except (FileNotFoundError, ValueError, Exception):
    return None
```

**Fix:**
```python
except (FileNotFoundError, ValueError, OSError, PermissionError) as e:
    logger.debug("Failed to read PID file %s: %s", pid_path, e)
    return None
```

**Test:** Add test case for OSError in read_pid_file()

---

#### Violation #3 (lines 180-181): cleanup_socket() silent failure

**Current code:**
```python
except Exception:
    pass
```

**Fix:**
```python
except (OSError, PermissionError) as e:
    logger.warning("Failed to cleanup socket %s: %s", socket_path, e)
except Exception as e:
    logger.error("Unexpected error cleaning socket %s: %s", socket_path, e, exc_info=True)
```

**Test:** Add test case for cleanup_socket() failure

---

#### Violation #4 (lines 195-196): cleanup_pid_file() silent failure

**Current code:**
```python
except Exception:
    pass
```

**Fix:**
```python
except (OSError, PermissionError) as e:
    logger.warning("Failed to cleanup PID file %s: %s", pid_path, e)
except Exception as e:
    logger.error("Unexpected error cleaning PID file %s: %s", pid_path, e, exc_info=True)
```

**Test:** Add test case for cleanup_pid_file() failure

**QA checkpoint:** Run `./scripts/qa/run_all.sh` after daemon/paths.py fixes

---

### Phase 1.2: daemon/memory_log_handler.py (1 violation)

**File:** src/claude_code_hooks_daemon/daemon/memory_log_handler.py

#### Violation #14 (lines 38-40): emit() broad exception

**Current code:**
```python
except Exception:
    self.handleError(record)
```

**Fix:**
```python
except (MemoryError, AttributeError, TypeError) as e:
    # Expected errors in append/access
    self.handleError(record)
except Exception as e:
    # Unexpected errors - log and reraise
    logger.error("Unexpected error in memory log handler: %s", e, exc_info=True)
    self.handleError(record)
```

**Test:** Add test for MemoryError handling

**QA checkpoint:** Run QA after this file

---

### Phase 1.3: daemon/validation.py (1 violation)

**File:** src/claude_code_hooks_daemon/daemon/validation.py

#### Violation #15 (lines 70-71): load_config_safe() silent failure

**Current code:**
```python
except Exception:
    return None
```

**Fix:**
```python
except (OSError, PermissionError, yaml.YAMLError) as e:
    logger.debug("Failed to load config from %s: %s", config_file, e)
    return None
except Exception as e:
    logger.error("Unexpected error loading config %s: %s", config_file, e, exc_info=True)
    return None
```

**Test:** Add test for config load failures

**QA checkpoint:** Run QA after Phase 1 complete

---

### Phase 2.1: handlers/pre_compact/workflow_state_pre_compact.py (6 violations)

**File:** src/claude_code_hooks_daemon/handlers/pre_compact/workflow_state_pre_compact.py

This file has **6 critical violations**. Fix systematically:

#### Violation #5 (lines 108-109): Silent JSON parse failure

**Current code:**
```python
except Exception:
    pass
```

**Fix:**
```python
except (OSError, json.JSONDecodeError, PermissionError) as e:
    logger.warning("Failed to read existing workflow state from %s: %s", state_file, e)
except Exception as e:
    logger.error("Unexpected error reading workflow state: %s", e, exc_info=True)
```

---

#### Violation #6 (lines 119-121): **CATASTROPHIC** fail-open

**Current code:**
```python
except Exception:
    # Fail open - if anything goes wrong, just allow compaction
    pass
```

**Fix:**
```python
except (OSError, json.JSONDecodeError, PermissionError) as e:
    logger.error("Workflow state preservation failed: %s", e, exc_info=True)
    # Return warning context to user
    return HookResult(
        decision=Decision.ALLOW,
        reason=None,
        context=[
            f"⚠️  WARNING: Failed to preserve workflow state: {e}",
            "Compaction proceeding but state may be lost."
        ]
    )
except Exception as e:
    logger.error("Unexpected error in workflow state handler: %s", e, exc_info=True)
    # Surface unexpected errors to user
    return HookResult(
        decision=Decision.DENY,
        reason=f"Workflow state handler encountered unexpected error: {e}",
        context=["Contact support if this persists."]
    )
```

**CRITICAL:** This changes behavior from silent failure to user-visible warning.

---

#### Violation #7 (lines 149-150): Silent CLAUDE.local.md read

**Current code:**
```python
except Exception:
    pass
```

**Fix:**
```python
except (OSError, PermissionError, UnicodeDecodeError) as e:
    logger.debug("Failed to read CLAUDE.local.md: %s", e)
except Exception as e:
    logger.error("Unexpected error reading CLAUDE.local.md: %s", e, exc_info=True)
```

---

#### Violation #8 (lines 168-169): Silent plan file read

**Current code:**
```python
except Exception:
    pass
```

**Fix:**
```python
except (OSError, PermissionError, UnicodeDecodeError) as e:
    logger.debug("Failed to read plan file %s: %s", plan_file, e)
except Exception as e:
    logger.error("Unexpected error reading plan file: %s", e, exc_info=True)
```

---

#### Violation #9 (lines 210-211): Silent memory parsing

**Current code:**
```python
except Exception:
    pass
```

**Fix:**
```python
except (ValueError, AttributeError) as e:
    logger.debug("Failed to parse workflow from CLAUDE.local.md: %s", e)
except Exception as e:
    logger.error("Unexpected error parsing CLAUDE.local.md: %s", e, exc_info=True)
```

---

#### Violation #10 (lines 223-224): Silent plan parsing

**Current code:**
```python
except Exception:
    pass
```

**Fix:**
```python
except (ValueError, AttributeError) as e:
    logger.debug("Failed to parse workflow from plan: %s", e)
except Exception as e:
    logger.error("Unexpected error parsing plan: %s", e, exc_info=True)
```

**QA checkpoint:** Run QA after workflow_state_pre_compact.py fixes

---

### Phase 2.2: handlers/session_start/workflow_state_restoration.py (1 violation)

**File:** src/claude_code_hooks_daemon/handlers/session_start/workflow_state_restoration.py

#### Violation #21 (lines 112-114): Silent restoration failure

**Current code:**
```python
except Exception:
    # Fail open on any error
    return HookResult(decision=Decision.ALLOW)
```

**Fix:**
```python
except (OSError, json.JSONDecodeError, PermissionError) as e:
    logger.warning("Workflow state restoration failed: %s", e, exc_info=True)
    return HookResult(
        decision=Decision.ALLOW,
        reason=None,
        context=[f"⚠️  Failed to restore workflow state: {e}"]
    )
except Exception as e:
    logger.error("Unexpected error in workflow restoration: %s", e, exc_info=True)
    return HookResult(
        decision=Decision.DENY,
        reason=f"Workflow restoration handler error: {e}",
        context=["Contact support if this persists."]
    )
```

**QA checkpoint:** Run QA after Phase 2 complete

---

### Phase 3: handlers/session_start/yolo_container_detection.py (4 violations)

**File:** src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py

#### Violation #17 (lines 114-116): _calculate_confidence_score() broad exception

**Current code:**
```python
except Exception:
    # Fail open - return 0 score on unexpected errors
    return 0
```

**Fix:**
```python
except (OSError, RuntimeError, AttributeError) as e:
    logger.debug("Confidence score calculation failed: %s", e)
    return 0
except Exception as e:
    logger.error("Unexpected error in confidence score: %s", e, exc_info=True)
    return 0
```

---

#### Violation #18 (lines 168-170): _get_triggered_indicators() broad exception

**Current code:**
```python
except Exception:
    # Fail open - return empty list on errors
    return []
```

**Fix:**
```python
except (OSError, RuntimeError, AttributeError) as e:
    logger.debug("Indicator detection failed: %s", e)
    return []
except Exception as e:
    logger.error("Unexpected error detecting indicators: %s", e, exc_info=True)
    return []
```

---

#### Violation #19 (lines 200-202): matches() broad exception

**Current code:**
```python
except Exception:
    # Fail open - don't match on errors
    return False
```

**Fix:**
```python
except (ValueError, TypeError, AttributeError) as e:
    logger.debug("YOLO match check failed: %s", e)
    return False
except Exception as e:
    logger.error("Unexpected error in YOLO matches(): %s", e, exc_info=True)
    return False
```

---

#### Violation #20 (lines 240-242): **CATASTROPHIC** handle() failure

**Current code:**
```python
except Exception:
    # Fail open - return ALLOW with no context on errors
    return HookResult(decision=Decision.ALLOW, reason=None, context=[])
```

**Fix:**
```python
except (OSError, RuntimeError, AttributeError) as e:
    logger.warning("YOLO container detection failed: %s", e, exc_info=True)
    return HookResult(
        decision=Decision.ALLOW,
        reason=None,
        context=[f"⚠️  YOLO detection failed: {e}"]
    )
except Exception as e:
    logger.error("YOLO handler encountered unexpected error: %s", e, exc_info=True)
    return HookResult(
        decision=Decision.DENY,
        reason=f"YOLO handler error: {e}",
        context=["Contact support if this persists."]
    )
```

**QA checkpoint:** Run QA after Phase 3 complete

---

### Phase 4.1: handlers/status_line/daemon_stats.py (1 violation)

**File:** src/claude_code_hooks_daemon/handlers/status_line/daemon_stats.py

#### Violation #11 (lines 68-69): Silent psutil failure

**Current code:**
```python
except Exception:
    pass
```

**Fix:**
```python
except (OSError, AttributeError) as e:
    logger.debug("Failed to get process memory: %s", e)
except Exception as e:
    logger.error("Unexpected error getting memory stats: %s", e, exc_info=True)
```

---

### Phase 4.2: handlers/status_line/git_branch.py (1 violation)

**File:** src/claude_code_hooks_daemon/handlers/status_line/git_branch.py

#### Violation #12 (lines 70-72): Silent git failure

**Current code:**
```python
except Exception:
    # Fail silently - git errors shouldn't break status line
    pass
```

**Fix:**
```python
except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
    logger.debug("Failed to get git branch: %s", e)
except Exception as e:
    logger.error("Unexpected error in git branch handler: %s", e, exc_info=True)
```

---

### Phase 4.3: handlers/stop/auto_continue_stop.py (1 violation)

**File:** src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py

#### Violation #16 (lines 159-160): Silent transcript read

**Current code:**
```python
except Exception:
    return ""
```

**Fix:**
```python
except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
    logger.debug("Failed to read transcript from %s: %s", transcript_path, e)
    return ""
except Exception as e:
    logger.error("Unexpected error reading transcript: %s", e, exc_info=True)
    return ""
```

---

### Phase 4.4: handlers/subagent_stop/remind_validator.py (1 violation)

**File:** src/claude_code_hooks_daemon/handlers/subagent_stop/remind_validator.py

#### Violation #22 (lines 171-172): Silent transcript parsing

**Current code:**
```python
except Exception:
    return ""
```

**Fix:**
```python
except (OSError, json.JSONDecodeError, AttributeError) as e:
    logger.debug("Failed to get last completed agent: %s", e)
    return ""
except Exception as e:
    logger.error("Unexpected error parsing agent info: %s", e, exc_info=True)
    return ""
```

**QA checkpoint:** Run QA after Phase 4 complete

---

### Phase 5: config/validator.py (1 violation)

**File:** src/claude_code_hooks_daemon/config/validator.py

#### Violation #13 (lines 112-114): Silent module import failure

**Current code:**
```python
except Exception:
    # Ignore import errors for individual modules
    pass
```

**Fix:**
```python
except (ImportError, SyntaxError, AttributeError) as e:
    logger.debug("Failed to import handler module %s: %s", modname, e)
except Exception as e:
    logger.error("Unexpected error importing %s: %s", modname, e, exc_info=True)
```

**QA checkpoint:** Run QA after Phase 5 complete

---

## Testing Strategy

### Unit Tests
For each fixed violation:
1. Add test case that triggers the specific exception
2. Verify logging occurs with correct level
3. Verify function returns expected default value
4. Verify unexpected exceptions are logged with exc_info=True

### Integration Tests
1. **Config validation test:** Invalid config surfaces clear error
2. **Daemon restart test:** After code changes, daemon picks up new code
3. **Error visibility test:** Critical handler failures visible to user

### Coverage Requirements
- Maintain 95%+ coverage throughout
- New exception paths must be tested
- Logging calls must be covered

---

## QA Checkpoints

After each phase:
```bash
./scripts/qa/run_all.sh
```

**Must pass:**
- Black formatting
- Ruff linting
- MyPy type checking
- Pytest (95%+ coverage)
- Bandit security scan

**If QA fails:** Fix immediately before proceeding to next phase.

---

## Deployment Checklist

After all fixes complete:

1. ✓ Run full QA suite
2. ✓ Commit changes with descriptive message
3. ✓ **Restart daemon** to load new code
4. ✓ Test daemon status: `python -m claude_code_hooks_daemon.daemon.cli status`
5. ✓ Test invalid config: Verify error surfaced
6. ✓ Test handler errors: Trigger known failure, verify logged
7. ✓ Integration test: Run through full hook lifecycle

---

## Rollback Plan

If critical issues discovered:
1. Revert commit
2. Restart daemon
3. Analyze failure
4. Fix and re-test

---

## Post-Fix Validation

### Smoke Tests
1. Daemon starts successfully
2. Config errors surface clearly
3. Handler failures logged
4. Status line works
5. All production handlers active

### Regression Tests
Run full test suite to ensure no functionality broken.

---

## Success Metrics

- ✓ 22/22 violations fixed
- ✓ All QA checks passing
- ✓ 95%+ test coverage maintained
- ✓ Daemon operational
- ✓ Error visibility improved
- ✓ No regressions

---

## Notes

- **Logging levels:**
  - DEBUG: Expected failures (FileNotFoundError, missing git repo)
  - WARNING: Recoverable errors (state save failed, continuing)
  - ERROR: Unexpected errors (exc_info=True for stack trace)

- **Exception specificity:**
  - Always use most specific exception type
  - Group related exceptions in tuple
  - Separate handler for unexpected exceptions

- **User visibility:**
  - Critical failures → DENY with clear reason
  - Recoverable failures → ALLOW with warning context
  - Expected failures → Silent (debug log only)

---

## Execution Command

To execute this plan:
```bash
# Phase by phase, or all at once
# Recommend: Execute phase-by-phase with QA between each
```

**Ready for execution.**
