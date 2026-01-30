# Plan 00016: Comprehensive Handler Integration Tests

**Status**: Not Started
**Created**: 2026-01-30
**Owner**: To be assigned
**Priority**: Critical (QA/reliability issue - handlers failing silently)
**Estimated Effort**: 8-12 hours

## Overview

Current integration test coverage is critically low: **9 test files covering 58 handler classes (15%)** and only 13.46% code coverage when running integration tests. This investigation revealed that handlers work correctly in unit tests but can fail silently in the live daemon due to initialization issues, event routing problems, or configuration errors.

This plan establishes comprehensive integration tests for ALL handlers using parametrized test patterns (data provider style) to verify they work correctly through the full daemon pipeline (EventRouter → HandlerChain → Handler).

## Goals

- Achieve **100% handler coverage** with integration tests (58/58 handlers)
- Use **parametrized tests** for multiple scenarios per handler (block/allow/edge cases)
- Test through **full event pipeline** (EventRouter + HandlerChain, not just Handler in isolation)
- Verify handlers **actually match** events they claim to handle
- Catch **initialization failures** that unit tests miss
- Establish **CI requirement** that new handlers must have integration tests

## Non-Goals

- Unit test coverage (already good, 95%+ maintained)
- End-to-end tests with actual daemon subprocess (too slow for CI)
- Performance testing (separate concern)
- Testing Claude Code's event generation (trust the protocol)

## Context & Background

### Critical Bug Discovery

Investigation of `ls | tail` not being blocked revealed:

1. **Handler logic is correct** - Unit tests pass, `PipeBlockerHandler.matches()` works
2. **Integration broken** - `PlanNumberHelperHandler` crashes during `__init__` with `RuntimeError: ProjectContext not initialized`
3. **Silent failure mode** - Daemon starts but handler registration fails, commands pass through unblocked
4. **Unit tests hide the bug** - Mock fixtures bypass initialization issues

### Current Integration Test Status

```bash
# Current state
Integration test files: 9
Handler classes: 58
Coverage: 15% of handlers, 13.46% of code

# Example impact
PipeBlockerHandler: 29% → 72% coverage with ONE integration test
```

### Gap Analysis

| Event Type | Handlers | Integration Tests | Coverage |
|------------|----------|-------------------|----------|
| PreToolUse | 20 | 1 (pipe_blocker) | 5% |
| PostToolUse | 4 | 0 | 0% |
| SessionStart | 3 | 0 | 0% |
| SessionEnd | 1 | 0 | 0% |
| PreCompact | 2 | 0 | 0% |
| UserPromptSubmit | 1 | 0 | 0% |
| PermissionRequest | 1 | 0 | 0% |
| Notification | 1 | 0 | 0% |
| Stop | 2 | 0 | 0% |
| SubagentStop | 3 | 0 | 0% |
| StatusLine | 6 | 0 | 0% |

**Total: 44 handlers need integration tests**

## Dependencies

### Blocks on Plan 00014 (CRITICAL)

**Plan 00014** must complete first because:

1. **ProjectContext initialization** - Fixes daemon startup crash
2. **Handler init pattern** - Establishes correct initialization order (daemon startup → ProjectContext.initialize() → handlers registered)
3. **Constants available** - `project_root`, `git_repo_name` must be available when handlers init

**Without 00014**: Cannot start daemon, cannot test handlers through full pipeline.

### Related Plans

- **Plan 00015** (SessionContext) - Nice-to-have but not blocking
- **Plan 00012** (Eliminate magic strings) - Improves test maintainability

## Tasks

### Phase 1: Fix Blocking Issues (Depends on Plan 00014)

- [ ] ⬜ **Task 1.1**: Wait for Plan 00014 completion
  - [ ] ⬜ ProjectContext initialized in DaemonController.initialise()
  - [ ] ⬜ Handler init pattern fixed (no ProjectContext calls in __init__)
  - [ ] ⬜ Daemon starts successfully
  - [ ] ⬜ Verify handlers load without crashes

- [ ] ⬜ **Task 1.2**: Establish integration test infrastructure
  - [ ] ⬜ Create `tests/integration/handlers/` directory structure
  - [ ] ⬜ Create base test class with EventRouter setup
  - [ ] ⬜ Create fixtures for common hook_input patterns
  - [ ] ⬜ Write helper functions for parametrized tests

### Phase 2: Safety Handlers (Priority 10-20)

- [ ] ⬜ **Task 2.1**: DestructiveGitHandler integration tests
  - [ ] ⬜ Test blocks: `git reset --hard`, `git clean -f`, `git push --force`
  - [ ] ⬜ Test allows: `git status`, `git add`, `git commit`
  - [ ] ⬜ Test terminal behavior (stops chain)
  - [ ] ⬜ Verify decision=deny with clear reason

- [ ] ⬜ **Task 2.2**: SedBlockerHandler integration tests
  - [ ] ⬜ Test blocks: `sed -i 's/foo/bar/' file.txt`
  - [ ] ⬜ Test allows: Read/Edit tools
  - [ ] ⬜ Test terminal behavior

- [ ] ⬜ **Task 2.3**: AbsolutePathHandler integration tests
  - [ ] ⬜ Test blocks: Read with relative path `tool_input.file_path="relative/path"`
  - [ ] ⬜ Test allows: Read with absolute path `/workspace/file.txt`
  - [ ] ⬜ Test all file tools: Read, Write, Edit, NotebookEdit

- [ ] ⬜ **Task 2.4**: WorktreeFileCopyHandler integration tests
  - [ ] ⬜ Test blocks: Copy between worktrees
  - [ ] ⬜ Test allows: Copy within same worktree
  - [ ] ⬜ Test edge cases: symlinks, non-git repos

- [ ] ⬜ **Task 2.5**: PipeBlockerHandler integration tests (EXTEND EXISTING)
  - [ ] ⬜ Add more scenarios: `npm test | tail`, `docker logs | head`
  - [ ] ⬜ Test whitelist: `grep | tail` allowed
  - [ ] ⬜ Test extraction logic with complex pipes

- [ ] ⬜ **Task 2.6**: GitStashHandler integration tests
  - [ ] ⬜ Test warns on `git stash`
  - [ ] ⬜ Test non-terminal (allows but warns)

### Phase 3: Code Quality Handlers (Priority 25-35)

- [ ] ⬜ **Task 3.1**: ESLintDisableHandler integration tests
  - [ ] ⬜ Test blocks: `/* eslint-disable */` in Write tool
  - [ ] ⬜ Test allows: Regular code
  - [ ] ⬜ Test edge cases: Comments in strings, already disabled

- [ ] ⬜ **Task 3.2**: TDDEnforcementHandler integration tests
  - [ ] ⬜ Test blocks: Implementation without tests
  - [ ] ⬜ Test allows: Test file writes
  - [ ] ⬜ Test pattern matching for test file detection

- [ ] ⬜ **Task 3.3**: QA Suppression Blockers (Python/PHP/Go)
  - [ ] ⬜ Test Python: `# noqa`, `# type: ignore`, `# pragma: no cover`
  - [ ] ⬜ Test PHP: `@codingStandardsIgnoreStart`, `@phpcs:disable`
  - [ ] ⬜ Test Go: `//nolint`, `// +build ignore`
  - [ ] ⬜ Test allows: Legitimate comments

- [ ] ⬜ **Task 3.4**: MarkdownOrganizationHandler integration tests
  - [ ] ⬜ Test CLAUDE/Plan directory enforcement
  - [ ] ⬜ Test plan workflow integration
  - [ ] ⬜ Test non-terminal accumulation

### Phase 4: Workflow Handlers (Priority 36-55)

- [ ] ⬜ **Task 4.1**: ValidatePlanNumberHandler integration tests
  - [ ] ⬜ Test blocks: Invalid plan numbers `Plan-001`, `plan_1`
  - [ ] ⬜ Test allows: Valid format `00001-`, `00015-`
  - [ ] ⬜ Test edge cases: Files in subdirectories

- [ ] ⬜ **Task 4.2**: PlanNumberHelperHandler integration tests
  - [ ] ⬜ Test provides context for next plan number
  - [ ] ⬜ Test reads CLAUDE/Plan directory
  - [ ] ⬜ Test non-terminal context accumulation

- [ ] ⬜ **Task 4.3**: PlanTimeEstimatesHandler integration tests
  - [ ] ⬜ Test blocks: Time estimates in plans
  - [ ] ⬜ Test regex patterns for all time formats

- [ ] ⬜ **Task 4.4**: PlanWorkflowHandler integration tests
  - [ ] ⬜ Test provides workflow guidance
  - [ ] ⬜ Test non-terminal advisory

- [ ] ⬜ **Task 4.5**: NpmCommandHandler integration tests
  - [ ] ⬜ Test blocks: `npm install`, `npm publish`
  - [ ] ⬜ Test allows: `npm test`, `npm audit`
  - [ ] ⬜ Test approval list

- [ ] ⬜ **Task 4.6**: GhIssueCommentsHandler integration tests
  - [ ] ⬜ Test provides gh CLI advice
  - [ ] ⬜ Test non-terminal advisory

### Phase 5: Tool Usage Handlers (Priority 50-60)

- [ ] ⬜ **Task 5.1**: WebSearchYearHandler integration tests
  - [ ] ⬜ Test fixes year in searches
  - [ ] ⬜ Test current year (2026)
  - [ ] ⬜ Test non-terminal modification

- [ ] ⬜ **Task 5.2**: BritishEnglishHandler integration tests
  - [ ] ⬜ Test warns on American spelling
  - [ ] ⬜ Test non-terminal advisory

### Phase 6: Post-Event Handlers

- [ ] ⬜ **Task 6.1**: BashErrorDetectorHandler integration tests
  - [ ] ⬜ Test detects errors in bash output
  - [ ] ⬜ Test exit codes
  - [ ] ⬜ Test stderr patterns

- [ ] ⬜ **Task 6.2**: ValidateESLintOnWriteHandler integration tests
  - [ ] ⬜ Test runs eslint after Write
  - [ ] ⬜ Test reports linting errors

- [ ] ⬜ **Task 6.3**: ValidateSitemapHandler integration tests
  - [ ] ⬜ Test validates sitemap structure
  - [ ] ⬜ Test PostToolUse event handling

### Phase 7: Session & State Handlers

- [ ] ⬜ **Task 7.1**: WorkflowStateRestorationHandler integration tests
  - [ ] ⬜ Test restores state on SessionStart
  - [ ] ⬜ Test reads state files

- [ ] ⬜ **Task 7.2**: WorkflowStatePreCompactHandler integration tests
  - [ ] ⬜ Test saves state on PreCompact
  - [ ] ⬜ Test writes state files

- [ ] ⬜ **Task 7.3**: YoloContainerDetectionHandler integration tests
  - [ ] ⬜ Test detects container environment
  - [ ] ⬜ Test confidence scoring

- [ ] ⬜ **Task 7.4**: TranscriptArchiverHandler integration tests
  - [ ] ⬜ Test archives transcript on PreCompact
  - [ ] ⬜ Test file writing

- [ ] ⬜ **Task 7.5**: CleanupHandler integration tests
  - [ ] ⬜ Test runs on SessionEnd
  - [ ] ⬜ Test cleanup operations

### Phase 8: User Interaction Handlers

- [ ] ⬜ **Task 8.1**: AutoApproveReadsHandler integration tests
  - [ ] ⬜ Test auto-approves read operations
  - [ ] ⬜ Test PermissionRequest event

- [ ] ⬜ **Task 8.2**: GitContextInjectorHandler integration tests
  - [ ] ⬜ Test injects git context on UserPromptSubmit
  - [ ] ⬜ Test context formatting

- [ ] ⬜ **Task 8.3**: NotificationLoggerHandler integration tests
  - [ ] ⬜ Test logs notifications
  - [ ] ⬜ Test Notification event

### Phase 9: Stop Handlers

- [ ] ⬜ **Task 9.1**: TaskCompletionCheckerHandler integration tests
  - [ ] ⬜ Test checks for incomplete tasks
  - [ ] ⬜ Test Stop event

- [ ] ⬜ **Task 9.2**: AutoContinueStopHandler integration tests
  - [ ] ⬜ Test auto-continues on confirmation questions
  - [ ] ⬜ Test reads transcript
  - [ ] ⬜ Test pattern matching

### Phase 10: Subagent Handlers

- [ ] ⬜ **Task 10.1**: SubagentCompletionLoggerHandler integration tests
  - [ ] ⬜ Test logs subagent completion
  - [ ] ⬜ Test SubagentStop event

- [ ] ⬜ **Task 10.2**: RemindValidatorHandler integration tests
  - [ ] ⬜ Test reminds about validation
  - [ ] ⬜ Test reads transcript

- [ ] ⬜ **Task 10.3**: RemindPromptLibraryHandler integration tests
  - [ ] ⬜ Test reminds about prompt library

### Phase 11: Status Line Handlers

- [ ] ⬜ **Task 11.1**: GitRepoNameHandler integration tests
  - [ ] ⬜ Test shows repo name
  - [ ] ⬜ Test reads ProjectContext
  - [ ] ⬜ Test non-terminal context accumulation

- [ ] ⬜ **Task 11.2**: AccountDisplayHandler integration tests
  - [ ] ⬜ Test shows account name
  - [ ] ⬜ Test reads .last-launch.conf

- [ ] ⬜ **Task 11.3**: ModelContextHandler integration tests
  - [ ] ⬜ Test shows model and context percentage
  - [ ] ⬜ Test color coding

- [ ] ⬜ **Task 11.4**: GitBranchHandler integration tests
  - [ ] ⬜ Test shows current branch
  - [ ] ⬜ Test git subprocess handling

- [ ] ⬜ **Task 11.5**: DaemonStatsHandler integration tests
  - [ ] ⬜ Test shows daemon stats
  - [ ] ⬜ Test memory display

- [ ] ⬜ **Task 11.6**: UsageTrackingHandler integration tests
  - [ ] ⬜ Test disabled state
  - [ ] ⬜ Test future implementation

### Phase 12: Test Infrastructure & CI

- [ ] ⬜ **Task 12.1**: Create parametrized test helper
  - [ ] ⬜ Build `@pytest.mark.parametrize` wrapper for handlers
  - [ ] ⬜ Support (hook_input, expected_decision, expected_reason) tuples
  - [ ] ⬜ Auto-generate test names

- [ ] ⬜ **Task 12.2**: Create common fixtures
  - [ ] ⬜ `router_with_handler(handler_class)` fixture
  - [ ] ⬜ `bash_hook_input(command)` fixture
  - [ ] ⬜ `write_hook_input(file_path, content)` fixture
  - [ ] ⬜ `read_hook_input(file_path)` fixture

- [ ] ⬜ **Task 12.3**: Add CI enforcement
  - [ ] ⬜ Require integration tests for new handlers
  - [ ] ⬜ Add coverage check for integration tests
  - [ ] ⬜ Update CONTRIBUTING.md

### Phase 13: Documentation & Completion

- [ ] ⬜ **Task 13.1**: Document integration test patterns
  - [ ] ⬜ Create CLAUDE/TESTING_HANDLERS.md
  - [ ] ⬜ Provide examples for each handler type
  - [ ] ⬜ Explain parametrized test usage

- [ ] ⬜ **Task 13.2**: Update handler development guide
  - [ ] ⬜ Update CLAUDE/HANDLER_DEVELOPMENT.md
  - [ ] ⬜ Add integration test section
  - [ ] ⬜ Add "Definition of Done" checklist

- [ ] ⬜ **Task 13.3**: Run full QA suite
  - [ ] ⬜ `./scripts/qa/run_all.sh`
  - [ ] ⬜ Verify 95%+ total coverage maintained
  - [ ] ⬜ Verify all integration tests pass

## Technical Decisions

### Decision 1: Test Style - Integration Through Router vs E2E

**Context**: How to test handlers in an integrated way?

**Options Considered**:
1. **EventRouter + HandlerChain** (chosen) - Fast, isolates event routing
2. **Full daemon subprocess** - Slow, tests entire stack
3. **FrontController** (legacy) - Deprecated, don't use

**Decision**: Use EventRouter + HandlerChain (Option 1) because:
- Fast enough for CI (milliseconds per test)
- Tests the actual production code path
- Isolates failures (router vs handler vs chain)
- Can mock external dependencies (git, filesystem)

**Date**: 2026-01-30

### Decision 2: Parametrized Tests vs Individual Test Functions

**Context**: 58 handlers × 3-5 scenarios = 200+ test cases. How to organize?

**Options Considered**:
1. **Parametrized with pytest.mark.parametrize** (chosen) - Data-driven, DRY
2. **Individual test functions** - Verbose, repetitive
3. **Test generators** - Complex, poor error messages

**Decision**: Parametrized tests (Option 1) because:
- Reduces code duplication (single test function, multiple data sets)
- Clear test names generated by pytest
- Easy to add new scenarios (just add tuple to list)
- Standard pytest pattern

**Example**:
```python
@pytest.mark.parametrize(
    "command,should_block,reason_contains",
    [
        ("ls | tail -5", True, "pipe"),
        ("find . | tail -10", True, "pipe"),
        ("grep error | tail", False, None),  # whitelisted
    ],
)
def test_pipe_blocker_scenarios(command, should_block, reason_contains):
    # Single test function, multiple scenarios
    ...
```

**Date**: 2026-01-30

### Decision 3: Mock vs Real Dependencies

**Context**: Handlers call git, read files, run subprocesses. Mock or use real?

**Options Considered**:
1. **Mock external calls** (chosen for most) - Fast, deterministic
2. **Real dependencies** (chosen for critical paths) - Slower, realistic
3. **Mix** - Mock non-critical, real for critical

**Decision**: Option 3 (Mix) because:
- **Mock**: git commands, filesystem I/O, subprocess calls (fast, reliable)
- **Real**: EventRouter, HandlerChain, Handler.matches/handle (actual code paths)
- **Real (selective)**: temp files for handlers that write (e.g., TranscriptArchiver)

**Date**: 2026-01-30

### Decision 4: Coverage Target

**Context**: What coverage % should integration tests achieve?

**Decision**:
- **Handler coverage**: 100% (58/58 handlers must have integration tests)
- **Code coverage**: Not enforced separately (unit tests cover 95%+)
- **Scenario coverage**: Minimum 3 scenarios per handler (block, allow, edge case)

**Rationale**: Integration tests catch initialization/routing bugs, not line coverage bugs.

**Date**: 2026-01-30

## Success Criteria

- [ ] **100% handler coverage**: All 58 handlers have integration tests
- [ ] **200+ test scenarios**: Minimum 3 scenarios per handler (58 × 3 = 174 minimum)
- [ ] **All tests pass**: `pytest tests/integration/handlers/` passes
- [ ] **No silent failures**: Handlers that should block actually block in tests
- [ ] **Fast CI**: Integration test suite completes in < 60 seconds
- [ ] **95%+ total coverage maintained**: QA suite still passes
- [ ] **Documentation updated**: Handler development guide includes integration test requirements
- [ ] **CI enforcement**: New handlers without integration tests fail CI

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Plan 00014 blocked/delayed | High | Medium | This plan can't start until 00014 completes; communicate dependency clearly |
| Tests too slow for CI | High | Low | Use mocks for external calls; optimize fixtures; run in parallel |
| Parametrized tests hide failures | Medium | Low | Ensure test names are descriptive; use `pytest -v` to show all scenarios |
| Mock drift from reality | Medium | Medium | Mix real/mock; update mocks when protocol changes; validate against real daemon |
| False positives (tests pass but daemon fails) | High | Low | Use EXACT hook_input format from real events; log events in DEBUG mode |

## Metrics to Track

- **Handler coverage %**: (handlers with integration tests) / 58
- **Test scenario count**: Total parametrized scenarios
- **Test execution time**: CI runtime for integration tests
- **Bug discovery rate**: Handlers that fail integration but pass unit tests
- **Code coverage delta**: Integration test impact on overall coverage %

## Notes & Updates

### 2026-01-30 - Plan Created

- Investigation revealed critical gap: 15% handler coverage, 13.46% code coverage
- Found initialization bug: PlanNumberHelperHandler crashes, daemon can't start
- Proved handler logic correct with unit tests, routing broken in daemon
- Created first integration test (pipe_blocker) - raised coverage from 29% → 72%
- Plan blocked on 00014 completion (ProjectContext initialization)

### Key Insight

**Unit tests are necessary but NOT sufficient** for handler validation. Integration tests catch:
- Initialization failures (ProjectContext not available)
- Event routing issues (wrong hook_input format)
- Silent failures (handler crashes, daemon continues)
- Configuration problems (handler not registered)

These bugs are INVISIBLE in unit tests because fixtures mock the environment.

## Example Test Pattern

```python
# tests/integration/handlers/test_pre_tool_use_safety.py

import pytest
from claude_code_hooks_daemon.core import EventRouter, EventType
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestPipeBlockerIntegration:
    """Integration tests for pipe blocker through full pipeline."""

    @pytest.mark.parametrize(
        "command,should_block,reason_contains",
        [
            # Should block (expensive commands)
            ("ls -la | tail -10", True, "pipe"),
            ("find . -name '*.py' | tail -5", True, "pipe"),
            ("npm test | head -20", True, "pipe"),
            ("docker logs container | tail", True, "pipe"),

            # Should allow (whitelisted)
            ("grep error log.txt | tail -20", False, None),
            ("awk '{print $1}' | head -10", False, None),
            ("jq '.data' file.json | tail", False, None),

            # Edge cases
            ("tail -f /var/log/syslog", False, None),  # tail -f allowed
            ("head -c 100 file.bin", False, None),  # head -c allowed
        ],
    )
    def test_pipe_blocker_scenarios(
        self, command: str, should_block: bool, reason_contains: str | None
    ) -> None:
        """Test pipe blocker with various commands."""
        # Setup
        router = EventRouter()
        router.register(EventType.PRE_TOOL_USE, PipeBlockerHandler())

        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }

        # Execute
        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify
        if should_block:
            assert result.result.decision == "deny", f"Should block: {command}"
            assert reason_contains in result.result.reason.lower()
            assert "pipe-blocker" in result.handlers_matched
        else:
            assert result.result.decision == "allow", f"Should allow: {command}"
```

---

**Maintained by**: Claude Code Hooks Daemon Contributors
**Last Updated**: 2026-01-30
