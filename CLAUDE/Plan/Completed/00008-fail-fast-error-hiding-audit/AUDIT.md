# Error Hiding Audit - Complete Findings

**Agent ID:** a2ffddb
**Date:** 2026-01-28
**Auditor:** Sonnet subagent
**Scope:** Entire src/claude_code_hooks_daemon/ codebase

## Executive Summary

**Total violations found: 22 CRITICAL, 2 MODERATE**

This is a **systemic failure** of the FAIL FAST principle. Error hiding patterns are pervasive throughout the codebase, with the most catastrophic violations in:
- Workflow state management (6 violations)
- YOLO container detection (4 violations)
- Daemon path operations (4 violations)

## Root Cause

The original daemon/cli.py violation that masked config errors:
```python
except Exception:
    # Config load failure - treat as normal install mode
    pass
```

This pattern was replicated throughout the codebase, leading to:
- Silent failures that mask errors
- Defaults to permissive behavior on failure
- No distinction between expected vs unexpected errors
- Users never informed when operations fail

---

## CRITICAL Violations (Silent failures that mask errors)

### 1. daemon/paths.py:126-127 - Broad exception swallowing in is_pid_alive
**File:** src/claude_code_hooks_daemon/daemon/paths.py
**Lines:** 126-127

```python
except PermissionError:
    # Process exists but we can't access it
    return True
except Exception:
    return False
```

**Why:** The `except Exception` catches ALL unexpected errors (AttributeError, OSError, etc.) and silently returns False. If os.kill() raises an unexpected error, we lose critical diagnostic information.

**Fix:** Remove the broad `except Exception`. Only catch specific known exceptions (ProcessLookupError, PermissionError). Unknown errors should propagate.

---

### 2. daemon/paths.py:152 - Triple exception handler hides parse errors
**File:** src/claude_code_hooks_daemon/daemon/paths.py
**Lines:** 152

```python
except (FileNotFoundError, ValueError, Exception):
    return None
```

**Why:** Catching `Exception` makes FileNotFoundError and ValueError redundant. Hides root causes like OSError, PermissionError, or encoding errors.

**Fix:** `except (FileNotFoundError, ValueError, OSError)` - be explicit about expected failure modes.

---

### 3. daemon/paths.py:180-181 - Silent socket cleanup failure
**File:** src/claude_code_hooks_daemon/daemon/paths.py
**Lines:** 180-181

```python
except Exception:
    pass
```

**Why:** If socket cleanup fails (PermissionError, OSError), error is completely invisible. User never knows cleanup failed.

**Fix:** Log the error: `logger.warning("Failed to cleanup socket %s: %s", socket_path, e)`

---

### 4. daemon/paths.py:195-196 - Silent PID file cleanup failure
**File:** src/claude_code_hooks_daemon/daemon/paths.py
**Lines:** 195-196

```python
except Exception:
    pass
```

**Why:** Same as above - PID file cleanup failures are invisible.

**Fix:** Log the error: `logger.warning("Failed to cleanup PID file %s: %s", pid_path, e)`

---

### 5. handlers/pre_compact/workflow_state_pre_compact.py:108-109 - Silent JSON parse failure
**File:** src/claude_code_hooks_daemon/handlers/pre_compact/workflow_state_pre_compact.py
**Lines:** 108-109

```python
try:
    with state_file.open() as f:
        old_state = json.load(f)
        workflow_state["created_at"] = old_state.get(
            "created_at", workflow_state["created_at"]
        )
except Exception:
    pass
```

**Why:** Corrupt JSON file or filesystem error silently ignored. User never knows state restoration failed.

**Fix:** Log warning: `logger.warning("Failed to read existing workflow state from %s: %s", state_file, e)`

---

### 6. handlers/pre_compact/workflow_state_pre_compact.py:119-121 - CATASTROPHIC fail-open
**File:** src/claude_code_hooks_daemon/handlers/pre_compact/workflow_state_pre_compact.py
**Lines:** 119-121

```python
except Exception:
    # Fail open - if anything goes wrong, just allow compaction
    pass
```

**Why:** ANY error in workflow state preservation is silently swallowed. Filesystem full? Silent. Permission denied? Silent. This violates FAIL FAST completely.

**Impact:** CATASTROPHIC - workflow state loss invisible to user.

**Fix:** Log error and consider failing the handler: `logger.error("Workflow state preservation failed: %s", e, exc_info=True)`

---

### 7. handlers/pre_compact/workflow_state_pre_compact.py:149-150 - Silent file read failure
**File:** src/claude_code_hooks_daemon/handlers/pre_compact/workflow_state_pre_compact.py
**Lines:** 149-150

```python
except Exception:
    pass
```

**Why:** CLAUDE.local.md read failure invisible. Could be corruption, permissions, encoding issues.

**Fix:** `logger.debug("Failed to read CLAUDE.local.md: %s", e)`

---

### 8. handlers/pre_compact/workflow_state_pre_compact.py:168-169 - Silent plan file read
**File:** src/claude_code_hooks_daemon/handlers/pre_compact/workflow_state_pre_compact.py
**Lines:** 168-169

```python
except Exception:
    pass
```

**Why:** Plan file read failures invisible.

**Fix:** `logger.debug("Failed to read plan file %s: %s", plan_file, e)`

---

### 9. handlers/pre_compact/workflow_state_pre_compact.py:210-211 - Silent memory parsing failure
**File:** src/claude_code_hooks_daemon/handlers/pre_compact/workflow_state_pre_compact.py
**Lines:** 210-211

```python
except Exception:
    pass
```

**Why:** CLAUDE.local.md parse errors invisible.

**Fix:** `logger.debug("Failed to parse workflow from CLAUDE.local.md: %s", e)`

---

### 10. handlers/pre_compact/workflow_state_pre_compact.py:223-224 - Silent plan parsing failure
**File:** src/claude_code_hooks_daemon/handlers/pre_compact/workflow_state_pre_compact.py
**Lines:** 223-224

```python
except Exception:
    pass
```

**Why:** Plan file parse errors invisible.

**Fix:** `logger.debug("Failed to parse workflow from plan: %s", e)`

---

### 11. handlers/status_line/daemon_stats.py:68-69 - Silent psutil failure
**File:** src/claude_code_hooks_daemon/handlers/status_line/daemon_stats.py
**Lines:** 68-69

```python
try:
    process = psutil.Process()
    mem_mb = process.memory_info().rss / (1024 * 1024)
    mem_str = f" | {mem_mb:.0f}MB"
except Exception:
    pass
```

**Why:** Any psutil error is invisible. Should at least log for debugging.

**Fix:** `logger.debug("Failed to get process memory: %s", e)`

---

### 12. handlers/status_line/git_branch.py:70-72 - Silent git command failure
**File:** src/claude_code_hooks_daemon/handlers/status_line/git_branch.py
**Lines:** 70-72

```python
except Exception:
    # Fail silently - git errors shouldn't break status line
    pass
```

**Why:** ALL git errors invisible. Could be corrupted repo, missing git binary, permission issues.

**Fix:** `logger.debug("Failed to get git branch: %s", e)`

---

### 13. config/validator.py:112-114 - Silent module import failure
**File:** src/claude_code_hooks_daemon/config/validator.py
**Lines:** 112-114

```python
try:
    module = importlib.import_module(modname)
    for attr_name in dir(module):
        # ... handler discovery ...
except Exception:
    # Ignore import errors for individual modules
    pass
```

**Why:** Module import errors are invisible. Could indicate broken handler code, missing dependencies, syntax errors.

**Fix:** `logger.debug("Failed to import handler module %s: %s", modname, e)`

---

### 14. daemon/memory_log_handler.py:38-40 - Exception in exception handler
**File:** src/claude_code_hooks_daemon/daemon/memory_log_handler.py
**Lines:** 38-40

```python
try:
    self.records.append(record)
except Exception:
    # Don't let logging errors break the daemon
    self.handleError(record)
```

**Why:** While handleError is appropriate, we should be more specific. What could fail in append()? MemoryError?

**Fix:** `except (MemoryError, AttributeError) as e:` - be specific about failure modes.

---

### 15. daemon/validation.py:70-71 - Silent git remote failure
**File:** src/claude_code_hooks_daemon/daemon/validation.py
**Lines:** 70-71

```python
except Exception:
    return None
```

**Why:** In `load_config_safe()`, YAML parsing errors are completely invisible.

**Fix:** `logger.debug("Failed to load config from %s: %s", config_file, e)` and return None.

---

### 16. handlers/stop/auto_continue_stop.py:159-160 - Silent transcript read failure
**File:** src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py
**Lines:** 159-160

```python
except Exception:
    return ""
```

**Why:** File read errors, JSON parse errors, all invisible. Could indicate corrupted transcript.

**Fix:** `logger.debug("Failed to read transcript from %s: %s", transcript_path, e)`

---

### 17. handlers/session_start/yolo_container_detection.py:114-116 - Silent filesystem errors
**File:** src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py
**Lines:** 114-116

```python
except Exception:
    # Fail open - return 0 score on unexpected errors
    return 0
```

**Why:** Broad exception in `_calculate_confidence_score()` hides unexpected errors.

**Fix:** Be specific - `except (OSError, RuntimeError, AttributeError) as e:` and log it.

---

### 18. handlers/session_start/yolo_container_detection.py:168-170 - Silent indicator detection failure
**File:** src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py
**Lines:** 168-170

```python
except Exception:
    # Fail open - return empty list on errors
    return []
```

**Why:** Same pattern - broad exception hides root causes.

**Fix:** Specific exceptions with logging.

---

### 19. handlers/session_start/yolo_container_detection.py:200-202 - Silent matches() failure
**File:** src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py
**Lines:** 200-202

```python
except Exception:
    # Fail open - don't match on errors
    return False
```

**Why:** Hides errors in match logic.

**Fix:** Specific exceptions: `except (ValueError, TypeError) as e:` and log.

---

### 20. handlers/session_start/yolo_container_detection.py:240-242 - CATASTROPHIC handle() failure
**File:** src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py
**Lines:** 240-242

```python
except Exception:
    # Fail open - return ALLOW with no context on errors
    return HookResult(decision=Decision.ALLOW, reason=None, context=[])
```

**Why:** CATASTROPHIC - if handle() throws ANY error, silently returns ALLOW. Could mask broken handler logic.

**Impact:** CATASTROPHIC - broken handler appears to work correctly.

**Fix:** Log error: `logger.error("YOLO container detection failed: %s", e, exc_info=True)` then return.

---

### 21. handlers/session_start/workflow_state_restoration.py:112-114 - Silent restoration failure
**File:** src/claude_code_hooks_daemon/handlers/session_start/workflow_state_restoration.py
**Lines:** 112-114

```python
except Exception:
    # Fail open on any error
    return HookResult(decision=Decision.ALLOW)
```

**Why:** Workflow state restoration errors completely invisible. User never knows restoration failed.

**Fix:** `logger.warning("Workflow state restoration failed: %s", e, exc_info=True)`

---

### 22. handlers/subagent_stop/remind_validator.py:171-172 - Silent transcript parsing failure
**File:** src/claude_code_hooks_daemon/handlers/subagent_stop/remind_validator.py
**Lines:** 171-172

```python
except Exception:
    return ""
```

**Why:** Transcript parse errors invisible.

**Fix:** `logger.debug("Failed to get last completed agent: %s", e)`

---

## MODERATE Violations (Overly broad handlers - should be specific)

### 23. daemon/validation.py:47-48 - Broad subprocess exception
**File:** src/claude_code_hooks_daemon/daemon/validation.py
**Lines:** 47-48

```python
except (subprocess.TimeoutExpired, FileNotFoundError):
    return False
```

**Why:** Should also catch `subprocess.CalledProcessError` for non-zero exit codes. Missing `OSError` for other filesystem issues.

**Fix:** `except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError, OSError):`

---

### 24. daemon/server.py:464-468 - Broad exception in client handler
**File:** src/claude_code_hooks_daemon/daemon/server.py
**Lines:** 464-468

```python
except Exception as e:
    logger.exception("Error handling client: %s", e)
    error_response = {"error": str(e)}
    writer.write((json.dumps(error_response) + "\n").encode())
    await writer.drain()
```

**Why:** While logged, this is too broad. Should catch specific exceptions (JSONDecodeError, asyncio.TimeoutError, etc).

**Fix:** Have separate handlers for known errors, let unknown errors propagate after logging.

---

## ACCEPTABLE Patterns (Not violations)

### 25. daemon/paths.py:149 - contextlib.suppress(Exception)
```python
with contextlib.suppress(Exception):
    pid_path.unlink()
```

**Why:** Intentional pattern for cleanup where failure is acceptable. Using `contextlib.suppress` makes intent clear.

**Status:** Acceptable - this pattern is fine for cleanup operations.

---

### 26. daemon/server.py:347-348 - asyncio.CancelledError suppression
```python
with contextlib.suppress(asyncio.CancelledError):
    await idle_monitor_task
```

**Why:** Correct pattern for handling task cancellation.

**Status:** Acceptable - idiomatic asyncio code.

---

## Systemic Issues

1. **Pattern replication:** The `except Exception: pass` pattern appears 22 times
2. **No logging:** Most handlers don't log failures, making debugging impossible
3. **Fail-open by default:** When errors occur, code defaults to permissive behavior
4. **No distinction:** Expected errors (FileNotFoundError) treated same as unexpected (AttributeError)
5. **User blindness:** Users never informed when operations fail

---

## Impact Analysis

**User-visible impact:**
- Config validation errors masked (daemon won't start, confusing error)
- Workflow state loss invisible (data loss)
- Handler failures silent (protection not active)
- Filesystem issues hidden (full disk, permissions)

**Developer impact:**
- Debugging nearly impossible (no error traces)
- Tests can't validate error handling (no errors propagate)
- Coverage metrics misleading (error paths untested)

---

## Recommended Fix Pattern

```python
# BEFORE (bad):
try:
    risky_operation()
except Exception:
    pass

# AFTER (good):
try:
    risky_operation()
except (FileNotFoundError, PermissionError) as e:
    logger.warning("Operation failed (continuing): %s", e)
except Exception:
    logger.error("Unexpected error in operation: %s", e, exc_info=True)
    raise  # Re-raise unexpected errors
```

---

## References

- **Original issue:** daemon/cli.py:120-122 (fixed)
- **Engineering principle violated:** FAIL FAST (CLAUDE.md line 11)
- **Agent ID:** a2ffddb (resume to continue audit work)
