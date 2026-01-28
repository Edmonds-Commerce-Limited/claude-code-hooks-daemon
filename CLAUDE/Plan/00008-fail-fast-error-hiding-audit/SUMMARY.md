# Executive Summary: Error Hiding Audit

**Date:** 2026-01-28
**Severity:** CRITICAL
**Status:** Ready for remediation

---

## The Problem

We discovered **systemic FAIL FAST violations** throughout the codebase:

```python
# This pattern appears 22 times
try:
    risky_operation()
except Exception:
    pass  # SILENT FAILURE
```

**Impact:**
- Config errors masked → confusing error messages
- Handler failures invisible → protection not active
- Data loss silent → workflow state disappears
- Debugging impossible → no error traces

---

## How We Got Here

1. **Original violation:** daemon/cli.py:120-122
   - Config validation errors swallowed
   - Pattern: `except Exception: pass`

2. **Pattern replicated:** Copied to 21 other locations
   - No code review caught it
   - No tests for error paths
   - Silent failures became standard practice

3. **Discovery trigger:** User reported:
   ```
   ERROR: This is the hooks-daemon repository.
   To run the daemon for development, add to .claude/hooks-daemon.yaml:
     daemon:
       self_install_mode: true
   ```

   **Real problem:** Invalid config schema, but error was masked.

---

## The Audit

**Sonnet agent scanned entire codebase** (Agent ID: a2ffddb)

**Found:**
- 22 CRITICAL violations (silent failures)
- 2 MODERATE violations (overly broad handlers)
- 2 ACCEPTABLE patterns (intentional, documented)

**Most critical:**
1. workflow_state_pre_compact.py - Data loss invisible
2. yolo_container_detection.py - Security handler fails silently
3. daemon/paths.py - Infrastructure errors hidden

---

## The Fix

**5-phase remediation plan:**

| Phase | Target | Violations | Impact |
|-------|--------|------------|--------|
| 1 | daemon/ core | 6 | Foundation |
| 2 | Workflow state | 7 | Data loss |
| 3 | Security (YOLO) | 4 | Safety |
| 4 | User-facing | 4 | UX |
| 5 | Config | 1 | Discovery |

**Fix pattern:**
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
    logger.warning("Operation failed: %s", e)
except Exception as e:
    logger.error("Unexpected error: %s", e, exc_info=True)
    raise  # Fail fast on unexpected errors
```

---

## Why This Matters

**Engineering principle violated:** FAIL FAST (CLAUDE.md:11)

> FAIL FAST - Detect errors early, validate at boundaries, explicit error handling

**Consequences of silent failures:**
1. **Users confused** - See wrong error messages
2. **Data lost** - Workflow state disappears silently
3. **Security bypassed** - Handlers fail but appear to work
4. **Debugging impossible** - No error traces

**The fix:**
1. **Specific exceptions** - Catch only expected errors
2. **Comprehensive logging** - Debug/warning/error levels
3. **Error visibility** - Surface critical failures to users
4. **Stack traces** - exc_info=True for unexpected errors

---

## Implementation Plan

**Execution strategy:** Phase-by-phase with QA checkpoints

**Timeline:**
- Phase 1: daemon/ core (foundational)
- Phase 2: Workflow state (data loss prevention)
- Phase 3: Security handlers (safety)
- Phase 4: User-facing (UX)
- Phase 5: Config (discovery)

**Quality gates:**
- QA after each phase (format, lint, types, tests, security)
- Maintain 95%+ test coverage
- Integration tests for error visibility

---

## Files in This Plan

1. **README.md** - Plan overview and quick start
2. **AUDIT.md** - Complete audit findings (22 violations documented)
3. **PLAN.md** - Detailed execution plan (phase-by-phase)
4. **CHECKLIST.md** - Execution tracking
5. **SUMMARY.md** - This file (executive summary)

---

## Next Steps

1. **Review:** Read PLAN.md for detailed fixes
2. **Execute:** Start with Phase 1 (daemon core)
3. **Validate:** Run QA after each phase
4. **Deploy:** Restart daemon after completion
5. **Verify:** Test error visibility improved

---

## Success Criteria

- ✓ 22/22 violations fixed
- ✓ All QA checks passing
- ✓ Errors surface to users
- ✓ Logging comprehensive
- ✓ No regressions
- ✓ Test coverage ≥95%

---

## References

- **Audit agent:** a2ffddb (Sonnet)
- **Trigger issue:** daemon/cli.py config masking
- **Engineering principles:** CLAUDE.md FAIL FAST
- **Standards:** 95% test coverage, strict type safety

---

**Ready for execution. Start with Phase 1 (daemon/).**
