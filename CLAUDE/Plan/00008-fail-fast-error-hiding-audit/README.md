# Plan 00008: FAIL FAST Error Hiding Audit & Remediation

**Status:** Ready for execution
**Priority:** CRITICAL
**Created:** 2026-01-28
**Agent ID:** a2ffddb (Sonnet audit agent)

---

## Overview

Comprehensive audit and remediation plan for **22 CRITICAL error hiding violations** throughout the codebase. These violations mask errors from users, making debugging impossible and violating the FAIL FAST principle.

---

## Quick Summary

**What was found:**
- 22 instances of `except Exception: pass` (silent failures)
- Broad exception handlers hiding root causes
- Config validation errors swallowed
- Handler failures invisible to users

**Root cause:**
- Pattern started in daemon/cli.py (config loading)
- Replicated throughout codebase systematically
- No distinction between expected vs unexpected errors

**Impact:**
- Users see confusing errors (wrong root cause)
- Debugging nearly impossible (no error traces)
- Data loss invisible (workflow state)
- Security handlers fail silently (YOLO detection)

---

## Files

### AUDIT.md
Complete audit findings from Sonnet agent:
- All 22 violations documented
- Code snippets with context
- Impact analysis
- Recommended fixes

### PLAN.md
Systematic execution plan:
- 5 phases organized by criticality
- Detailed fixes for each violation
- Testing strategy
- QA checkpoints
- Deployment checklist

---

## Phases

| Phase | Files | Violations | Priority |
|-------|-------|------------|----------|
| 1 | daemon/ (3 files) | 6 | High - Core infrastructure |
| 2 | handlers/pre_compact + session_start (2 files) | 7 | Critical - Data loss risk |
| 3 | handlers/session_start/yolo (1 file) | 4 | High - Security |
| 4 | handlers/status_line + stop (4 files) | 4 | Medium - UX |
| 5 | config/ (1 file) | 1 | Medium - Discovery |
| **Total** | **11 files** | **22 violations** | |

---

## Most Critical Violations

### 🔴 CATASTROPHIC

1. **workflow_state_pre_compact.py:119-121**
   Any error in state preservation silently swallowed → data loss invisible

2. **yolo_container_detection.py:240-242**
   Handler failure returns ALLOW → broken security handler appears to work

3. **daemon/cli.py:120-122** (ALREADY FIXED)
   Config validation errors masked → confusing error messages

### 🟠 HIGH IMPACT

4. **daemon/paths.py** (4 violations)
   Cleanup failures invisible, PID check errors hidden

5. **workflow_state_restoration.py:112-114**
   State restoration failures silent

---

## Execution Strategy

**Recommended:** Phase-by-phase with QA between each

```bash
# 1. Review plan
cat CLAUDE/Plan/00008-fail-fast-error-hiding-audit/PLAN.md

# 2. Execute Phase 1 (daemon core)
# - Fix daemon/paths.py
# - Fix daemon/memory_log_handler.py
# - Fix daemon/validation.py
# - Run QA

# 3. Execute Phase 2 (workflow state)
# - Fix workflow_state_pre_compact.py
# - Fix workflow_state_restoration.py
# - Run QA

# 4. Continue phases 3-5...

# 5. Final validation
./scripts/qa/run_all.sh
python -m claude_code_hooks_daemon.daemon.cli restart
python -m claude_code_hooks_daemon.daemon.cli status
```

---

## Testing Requirements

**Unit tests:**
- Test each specific exception type
- Verify logging at correct level
- Verify default return values

**Integration tests:**
- Config validation surfaces errors
- Daemon restart picks up new code
- Handler failures visible to user

**Coverage:**
- Maintain 95%+ throughout
- New exception paths covered

---

## Success Criteria

- ✓ All 22 violations fixed
- ✓ QA passing (format, lint, types, tests, security)
- ✓ Daemon operational
- ✓ Errors surface to users
- ✓ Logging comprehensive
- ✓ No regressions

---

## References

- **Engineering principles:** CLAUDE.md (FAIL FAST line 11)
- **Original trigger:** daemon/cli.py config validation bug
- **Audit agent:** a2ffddb (resume with Task tool if needed)

---

## Next Steps

1. Review PLAN.md for detailed execution steps
2. Start with Phase 1 (daemon core)
3. Run QA after each phase
4. Restart daemon after all fixes
5. Validate errors now surface correctly

**Ready to execute.**
