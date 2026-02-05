# Execution Checklist

Track progress fixing all 22 error hiding violations.

---

## Phase 1: Core Infrastructure (daemon/)

### daemon/paths.py (4 violations)
- [ ] #1: is_pid_alive() broad exception (line 126-127)
- [ ] #2: read_pid_file() triple exception (line 152)
- [ ] #3: cleanup_socket() silent failure (line 180-181)
- [ ] #4: cleanup_pid_file() silent failure (line 195-196)
- [ ] QA checkpoint passed

### daemon/memory_log_handler.py (1 violation)
- [ ] #14: emit() broad exception (line 38-40)
- [ ] QA checkpoint passed

### daemon/validation.py (1 violation)
- [ ] #15: load_config_safe() silent failure (line 70-71)
- [ ] QA checkpoint passed

**Phase 1 Complete:** [ ]

---

## Phase 2: Critical Handlers (workflow state)

### handlers/pre_compact/workflow_state_pre_compact.py (6 violations)
- [ ] #5: Silent JSON parse failure (line 108-109)
- [ ] #6: **CATASTROPHIC** fail-open (line 119-121)
- [ ] #7: Silent CLAUDE.local.md read (line 149-150)
- [ ] #8: Silent plan file read (line 168-169)
- [ ] #9: Silent memory parsing (line 210-211)
- [ ] #10: Silent plan parsing (line 223-224)
- [ ] QA checkpoint passed

### handlers/session_start/workflow_state_restoration.py (1 violation)
- [ ] #21: Silent restoration failure (line 112-114)
- [ ] QA checkpoint passed

**Phase 2 Complete:** [ ]

---

## Phase 3: Safety Handlers (container detection)

### handlers/session_start/yolo_container_detection.py (4 violations)
- [ ] #17: _calculate_confidence_score() broad exception (line 114-116)
- [ ] #18: _get_triggered_indicators() broad exception (line 168-170)
- [ ] #19: matches() broad exception (line 200-202)
- [ ] #20: **CATASTROPHIC** handle() failure (line 240-242)
- [ ] QA checkpoint passed

**Phase 3 Complete:** [ ]

---

## Phase 4: User-Facing Handlers

### handlers/status_line/daemon_stats.py (1 violation)
- [ ] #11: Silent psutil failure (line 68-69)
- [ ] QA checkpoint passed

### handlers/status_line/git_branch.py (1 violation)
- [ ] #12: Silent git failure (line 70-72)
- [ ] QA checkpoint passed

### handlers/stop/auto_continue_stop.py (1 violation)
- [ ] #16: Silent transcript read (line 159-160)
- [ ] QA checkpoint passed

### handlers/subagent_stop/remind_validator.py (1 violation)
- [ ] #22: Silent transcript parsing (line 171-172)
- [ ] QA checkpoint passed

**Phase 4 Complete:** [ ]

---

## Phase 5: Configuration

### config/validator.py (1 violation)
- [ ] #13: Silent module import failure (line 112-114)
- [ ] QA checkpoint passed

**Phase 5 Complete:** [ ]

---

## Final Validation

### QA Suite
- [ ] Black formatting passed
- [ ] Ruff linting passed
- [ ] MyPy type checking passed
- [ ] Pytest passed (95%+ coverage)
- [ ] Bandit security scan passed

### Deployment
- [ ] All code committed
- [ ] Daemon restarted
- [ ] Daemon status check passed
- [ ] Invalid config test passed
- [ ] Handler error test passed
- [ ] Integration tests passed

### Verification
- [ ] Errors surface to users
- [ ] Logging comprehensive
- [ ] No regressions detected
- [ ] All handlers operational

---

## Completion

**Total violations fixed:** 0 / 22

**Status:** Not started

**Completion date:** ___________

---

## Notes

Add notes here during execution:

