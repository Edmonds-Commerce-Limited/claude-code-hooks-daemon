# Acceptance Testing Playbook Implementation Plan

## Overview

Create a Claude Code-executable acceptance testing playbook to validate that hooks work correctly in real-world usage. Current tests (2,699 unit tests, 108 integration tests) use mock hook inputs and don't catch real-world integration issues. This playbook will use actual Claude Code sessions to test all 54 handlers across 11 event types.

## Problem Statement

Despite comprehensive unit and integration tests with 95%+ coverage, handlers sometimes don't work as expected in actual Claude Code sessions because:
- Tests use mock hook inputs constructed by developers, not real Claude Code event formats
- No validation against actual Claude Code CLI behavior
- Gap between unit tests (isolated) and real daemon usage (integrated with Claude Code)

## Solution

**Hybrid acceptance testing playbook** combining:
- Markdown playbook with step-by-step instructions Claude Code can follow
- Automated test scenario scripts (bash) that trigger real hook events
- Validation automation (Python) that parses daemon logs for pass/fail
- Tiered approach: Quick smoke test (20 min) + comprehensive suite (2 hours)

## Critical Files to Create

1. `/workspace/CLAUDE/AcceptanceTests/PLAYBOOK.md` - Main playbook for Claude Code to follow
2. `/workspace/CLAUDE/AcceptanceTests/run-tier1.sh` - Tier 1 orchestration (critical path)
3. `/workspace/CLAUDE/AcceptanceTests/run-tier2.sh` - Tier 2 orchestration (comprehensive)
4. `/workspace/CLAUDE/AcceptanceTests/test-scenarios/01-safety-blockers.sh` - Safety handler tests
5. `/workspace/CLAUDE/AcceptanceTests/test-scenarios/02-qa-enforcement.sh` - QA enforcement tests
6. `/workspace/CLAUDE/AcceptanceTests/test-scenarios/03-workflow-handlers.sh` - Workflow tests
7. `/workspace/CLAUDE/AcceptanceTests/test-scenarios/04-advisory-handlers.sh` - Advisory tests
8. `/workspace/CLAUDE/AcceptanceTests/test-scenarios/05-complete-workflows.sh` - End-to-end workflows
9. `/workspace/CLAUDE/AcceptanceTests/validation/validate-logs.py` - Log parser and validator
10. `/workspace/CLAUDE/AcceptanceTests/validation/expected-responses.yaml` - Expected handler responses
11. `/workspace/CLAUDE/AcceptanceTests/validation/test-helpers.sh` - Bash helper functions

## Directory Structure

```
CLAUDE/AcceptanceTests/
├── PLAYBOOK.md                    # Main playbook (Claude Code follows this)
├── run-tier1.sh                   # Quick smoke test (15-20 handlers)
├── run-tier2.sh                   # Comprehensive suite (50+ handlers)
├── test-scenarios/
│   ├── 01-safety-blockers.sh      # DestructiveGit, SedBlocker, PipeBlocker, AbsolutePath
│   ├── 02-qa-enforcement.sh       # TDD, ESLint, Python/Go QA suppressions
│   ├── 03-workflow-handlers.sh    # Planning, workflow state, git context
│   ├── 04-advisory-handlers.sh    # British English, web search year, bash errors
│   └── 05-complete-workflows.sh   # Full TDD cycle, git workflow, planning
├── validation/
│   ├── validate-logs.py           # Parse daemon logs, check expected responses
│   ├── expected-responses.yaml    # Single source of truth for handler behavior
│   └── test-helpers.sh            # Bash utilities (setup, cleanup, assertions)
├── fixtures/
│   ├── test-files/                # Sample code files for testing
│   └── test-repos/                # Git repo fixtures
└── results/
    └── YYYY-MM-DD-HH-MM-SS/       # Timestamped results directory
        ├── execution.log          # Full execution log
        ├── daemon-logs.txt        # Daemon debug logs from debug_hooks.sh
        ├── summary.md             # Pass/fail summary
        └── scenario-*.log         # Individual scenario logs
```

## Handler Priority Matrix (Tier 1: Critical Path)

**15 Critical Handlers to Test First:**

| Handler | Event | Priority | Type | Test Scenario |
|---------|-------|----------|------|---------------|
| DestructiveGitHandler | PreToolUse | 10 | BLOCKING | `git reset --hard`, `git clean -f`, `git push --force` |
| SedBlockerHandler | PreToolUse | 11 | BLOCKING | `sed -i 's/foo/bar/'` in bash/files |
| PipeBlockerHandler | PreToolUse | 12 | BLOCKING | `npm test \| tail`, `find \| head` |
| AbsolutePathHandler | PreToolUse | 20 | BLOCKING | Read/Write/Edit with relative paths |
| TddEnforcementHandler | PreToolUse | 25 | BLOCKING | Create handler without test file |
| EslintDisableHandler | PreToolUse | 30 | BLOCKING | Write `// eslint-disable` |
| PythonQaSuppressionBlocker | PreToolUse | 28 | BLOCKING | Write `# noqa`, `# type: ignore` |
| GoQaSuppressionBlocker | PreToolUse | 29 | BLOCKING | Write `// nolint` |
| PlanWorkflowHandler | PreToolUse | 48 | ADVISORY | Write to PLAN.md files |
| GitContextInjectorHandler | UserPromptSubmit | — | CONTEXT | User prompt submission |
| WorkflowStateRestorationHandler | SessionStart | — | CONTEXT | Session start after compact |
| BashErrorDetectorHandler | PostToolUse | — | ADVISORY | Bash command with exit code 1 |
| BritishEnglishHandler | PreToolUse | 56 | ADVISORY | Write "color" in markdown |
| WebSearchYearHandler | PreToolUse | 50 | ADVISORY | WebSearch with "2023" |
| DaemonStatsHandler | StatusLine | 30 | CONTEXT | Status line generation |

## Implementation Phases

### Phase 1: Directory Setup & Core Infrastructure (2 hours)

**Tasks:**
- Create directory structure: `CLAUDE/AcceptanceTests/` with subdirectories
- Create `fixtures/test-files/` with sample files (Python handlers, TypeScript, markdown)
- Create `validation/test-helpers.sh` with setup/cleanup/assertion functions
- Initialize `results/.gitkeep` (results/ should be gitignored)

**Deliverables:**
- Directory structure exists
- Test fixtures ready
- Helper functions available

### Phase 2: Validation Framework (3 hours)

**Tasks:**
- Create `validation/expected-responses.yaml` with handler specifications
- Implement `validation/validate-logs.py`:
  - Parse daemon debug logs
  - Extract handler execution events (handler name, decision, reason)
  - Compare against expected responses
  - Output pass/fail with clear diagnostics
- Test validation script with existing debug logs

**Deliverables:**
- `expected-responses.yaml` with 15+ handlers defined
- `validate-logs.py` working with sample logs
- Unit tests for validation script (pytest)

### Phase 3: Test Scenarios (4 hours)

**Tasks:**
- Implement `test-scenarios/01-safety-blockers.sh`:
  - Test 1: DestructiveGitHandler (git reset --hard, git clean -f, git push --force)
  - Test 2: SedBlockerHandler (sed -i in various contexts)
  - Test 3: PipeBlockerHandler (expensive command pipes)
  - Test 4: AbsolutePathHandler (relative vs absolute paths)
- Implement `test-scenarios/02-qa-enforcement.sh`:
  - Test 1: TddEnforcementHandler (handler without test)
  - Test 2: EslintDisableHandler (suppress ESLint)
  - Test 3: PythonQaSuppressionBlocker (# noqa, # type: ignore)
  - Test 4: GoQaSuppressionBlocker (// nolint)
- Implement `test-scenarios/03-workflow-handlers.sh`:
  - Test 1: PlanWorkflowHandler (create PLAN.md)
  - Test 2: GitContextInjectorHandler (user prompt submission)
  - Test 3: WorkflowStateRestorationHandler (session start)
- Implement `test-scenarios/04-advisory-handlers.sh`:
  - Test 1: BritishEnglishHandler (American spellings)
  - Test 2: WebSearchYearHandler (outdated year)
  - Test 3: BashErrorDetectorHandler (failing commands)
- Each script includes:
  - Setup (create test files, git commits)
  - Test actions (attempt operations)
  - Inline validation checks
  - Cleanup

**Deliverables:**
- 4 scenario scripts working independently
- Each test documented with expected outcomes
- Cleanup code to restore environment

### Phase 4: Main Playbook & Orchestration (2 hours)

**Tasks:**
- Create `PLAYBOOK.md`:
  - Prerequisites checklist
  - Quick start commands
  - Step-by-step execution workflow
  - Scenario descriptions with validation criteria
  - Troubleshooting guide
  - Result interpretation guide
- Create `run-tier1.sh`:
  - Start daemon debug logging via `./scripts/debug_hooks.sh start`
  - Execute critical path scenarios (01-04)
  - Stop debug logging via `./scripts/debug_hooks.sh stop`
  - Copy logs to results directory
  - Run validation script
  - Generate summary report
- Create `run-tier2.sh`:
  - All of Tier 1 plus scenario 05 (complete workflows)
  - Extended validation for all 54 handlers

**Deliverables:**
- `PLAYBOOK.md` complete and clear
- `run-tier1.sh` working end-to-end
- `run-tier2.sh` working end-to-end
- Results directory structure created

### Phase 5: Complete Workflows & Documentation (2 hours)

**Tasks:**
- Implement `test-scenarios/05-complete-workflows.sh`:
  - Full TDD cycle (write test, create handler, verify)
  - Git workflow (commit, attempt force push, create PR)
  - Planning workflow (create plan, validate numbering, complete)
- Add comprehensive documentation to `PLAYBOOK.md`:
  - Example test execution session
  - Pass/fail interpretation
  - Common failure modes and fixes
- Create `CLAUDE/AcceptanceTests/README.md` overview
- Update `CLAUDE/ARCHITECTURE.md` with acceptance testing section

**Deliverables:**
- Complete workflows scenario working
- Documentation comprehensive
- README with quick reference

### Phase 6: Integration & Testing (2-3 hours)

**Tasks:**
- Run full Tier 1 acceptance tests via Claude Code session
- Document any failures and fix root causes
- Run full Tier 2 acceptance tests
- Validate all 15 critical handlers pass
- Create baseline results for comparison
- Add acceptance tests to `scripts/qa/run_all.sh` (optional)

**Deliverables:**
- All Tier 1 tests passing
- Documented baseline results
- Any issues fixed

## Validation Approach

### Automated Validation (validate-logs.py)

```python
# Parses daemon debug logs to extract:
1. Handler execution events (handler name, priority, decision)
2. Hook input/output (tool name, decision, reason)
3. Timing and performance metrics

# Validates against expected-responses.yaml:
- Handler executed for matching pattern
- Decision matches expected (deny/allow)
- Reason message contains expected keywords
- Handler priority correct
- Terminal flag respected (chain stops or continues)
```

### Manual Validation (Claude Code)

```
Claude Code observes:
1. Blocked commands actually fail (not executed)
2. Warning messages are clear and helpful
3. Status line displays expected information
4. Context injection appears in responses
5. Workflow state restoration works correctly
```

## Expected Responses Format (expected-responses.yaml)

```yaml
handlers:
  destructive-git:
    event_type: PreToolUse
    priority: 10
    terminal: true
    tests:
      - pattern: "git reset --hard"
        decision: deny
        reason_contains: ["destroys all uncommitted changes", "permanently"]
      - pattern: "git clean -f"
        decision: deny
        reason_contains: ["permanently deletes untracked files"]
      - pattern: "git push --force"
        decision: deny
        reason_contains: ["overwrite remote history"]

  sed-blocker:
    event_type: PreToolUse
    priority: 11
    terminal: true
    tests:
      - pattern: "sed -i 's/foo/bar/' file.txt"
        decision: deny
        reason_contains: ["sed", "Edit tool", "parallel haiku"]
```

## Test Execution Workflow for Claude Code

1. **Prerequisites Check:**
   ```bash
   # Claude Code runs:
   $PYTHON -m claude_code_hooks_daemon.daemon.cli status  # Must be RUNNING
   git status  # Must be clean working tree
   ```

2. **Execute Tier 1:**
   ```bash
   # Claude Code runs:
   ./CLAUDE/AcceptanceTests/run-tier1.sh

   # Observes output:
   # - Each scenario executes
   # - Daemon logs captured
   # - Validation results shown
   ```

3. **Review Results:**
   ```bash
   # Claude Code reads:
   cat CLAUDE/AcceptanceTests/results/latest/summary.md

   # Shows:
   # ✓ PASS: destructive-git (3/3 tests)
   # ✓ PASS: sed-blocker (4/4 tests)
   # ✗ FAIL: pipe-blocker (2/3 tests) - Test 3 failed
   ```

4. **Debug Failures:**
   ```bash
   # Claude Code investigates:
   cat CLAUDE/AcceptanceTests/results/latest/daemon-logs.txt | grep pipe-blocker
   # Identifies root cause, fixes handler or test
   ```

## Success Criteria

- [ ] All 15 Tier 1 handlers pass acceptance tests
- [ ] Playbook is clear enough for Claude Code to follow without clarification
- [ ] Validation script correctly identifies pass/fail
- [ ] Results documented in timestamped directories
- [ ] Test execution completes in < 20 minutes (Tier 1)
- [ ] Tests use real Claude Code events (via debug_hooks.sh)
- [ ] Pass/fail criteria are objective and automatable
- [ ] Documentation explains how to add new test scenarios

## Integration with Existing Infrastructure

**Reuses:**
- `scripts/debug_hooks.sh` for daemon log capture
- Existing daemon lifecycle management
- Existing handler implementations (no changes needed)
- Existing QA infrastructure (pytest for validation script)

**Complements:**
- Unit tests: Handler logic in isolation
- Integration tests: Daemon lifecycle and config loading
- Acceptance tests: Real-world Claude Code usage (NEW)

**Documents:**
- Real handler behavior for developers
- Expected user experience for each handler
- Baseline for regression testing

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Daemon restart during testing disrupts session | High | Use debug_hooks.sh which handles restart gracefully |
| Log parsing fragile to log format changes | Medium | Use structured logging, version expected-responses.yaml |
| Tests too slow (> 30 min for Tier 1) | Medium | Parallelize independent scenarios, optimize setup/cleanup |
| False positives (tests pass but handlers broken) | High | Include manual validation steps, test negative cases |
| Tests require manual intervention | Medium | Automate setup/cleanup, provide clear error messages |

## Estimated Effort

- **Total Implementation**: 15-18 hours
  - Phase 1: 2 hours
  - Phase 2: 3 hours
  - Phase 3: 4 hours
  - Phase 4: 2 hours
  - Phase 5: 2 hours
  - Phase 6: 2-3 hours

- **Execution Time**:
  - Tier 1: 15-20 minutes
  - Tier 2: 1.5-2 hours
  - Per-handler debug: 5-10 minutes

## Future Enhancements

- Add visual indicators (colors) for pass/fail in terminal
- Screenshot capture for visual handlers (status line)
- Parallel test execution for independent scenarios
- CI/CD integration (run acceptance tests nightly)
- Benchmark performance (handler latency)
- Coverage report (which handlers tested, which skipped)

## Verification Steps

After implementation, verify by:

1. Running Tier 1 in fresh Claude Code session
2. Confirming all 15 critical handlers pass
3. Intentionally breaking a handler (e.g., disable destructive-git)
4. Confirming acceptance test catches the failure
5. Documenting baseline results for future comparison
