# Plan 00025: Programmatic Acceptance Testing System

**Status**: Not Started
**Created**: 2026-02-02
**Owner**: To be assigned
**Priority**: High
**GitHub Issue**: #18

## Overview

Create a programmatic acceptance testing system where handlers define their own test cases as code, enabling automatic playbook generation and future automated testing. This eliminates duplication between handler code and acceptance tests, provides type safety, and makes tests config-aware.

Currently, acceptance tests are maintained manually in `CLAUDE/AcceptanceTests/PLAYBOOK.md`, requiring manual updates when handlers change and providing no programmatic validation.

## Goals

- Create `AcceptanceTest` dataclass for type-safe test definitions
- Extend Handler base class with `get_acceptance_tests()` method (optional, backward compatible)
- Implement playbook generator that aggregates tests from all enabled handlers
- Create `generate-playbook` CLI command
- Migrate all 54 built-in handlers to define their acceptance tests programmatically
- Support custom plugin handlers automatically
- Maintain 95%+ test coverage throughout

## Non-Goals

- Automated execution of acceptance tests (foundation only, automation is future work)
- Changing existing handler behavior or priorities
- Modifying manual PLAYBOOK.md format (must match exactly for compatibility)
- Breaking backward compatibility with existing handlers

## Context & Background

### Current Acceptance Testing (Manual)

**Location**: `CLAUDE/AcceptanceTests/PLAYBOOK.md`
- 15 test scenarios covering all handler types
- Manual execution required per release
- Test definitions duplicated between playbook and handler code
- Triple-layer safety (echo, hooks, fail-safe args)
- FAIL-FAST principle: any bug found → fix with TDD → restart from Test 1.1

**Format Example**:
```markdown
## Test N: HandlerName
**Handler ID**: handler-id
**Event**: PreToolUse
**Priority**: XX
**Type**: Blocking (terminal=true)

### Test N.1: Description
**Command**: echo "command"
**Expected**: BLOCKED with message about X
**Result**: [ ] PASS [ ] FAIL
**Safety**: Uses non-existent ref - harmless if executed
```

### Handler Ecosystem

- **54 handlers** across 9 event types (PreToolUse, PostToolUse, SessionStart, etc.)
- **Handler types**: Terminal blocking, Non-terminal advisory, Context injection
- **Priority ranges**: 10-20 (safety), 25-35 (QA), 40-55 (workflow), 56-60 (advisory)
- **Plugin support**: Custom handlers can be added via plugins

### Pain Points with Manual Approach

1. **Duplication**: Patterns exist in both handler code and playbook markdown
2. **Manual Sync**: Adding handler requires manual playbook update (error-prone)
3. **No Type Safety**: Markdown not validated programmatically
4. **Plugin Blindness**: No standardized way for custom plugins to define tests
5. **Config Unawareness**: Playbook doesn't know which handlers are enabled
6. **Future Automation Blocked**: Can't automate without structured definitions

## Tasks

### Phase 1: Core Infrastructure (TDD)

- [ ] **Task 1.1**: Create `AcceptanceTest` dataclass with validation
  - [ ] Write failing tests for dataclass structure
  - [ ] Create `src/claude_code_hooks_daemon/core/acceptance_test.py`
  - [ ] Implement `AcceptanceTest` dataclass with all fields
  - [ ] Add `TestType` enum (BLOCKING, ADVISORY, CONTEXT)
  - [ ] Add validation for required fields
  - [ ] Verify 95%+ coverage
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 1.2**: Extend Handler base class
  - [ ] Write failing tests for `get_acceptance_tests()` method
  - [ ] Add optional method to `Handler` base class returning `list[AcceptanceTest]`
  - [ ] Default implementation returns empty list (backward compatible)
  - [ ] Verify existing handlers unaffected
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 1.3**: Create PlaybookGenerator core
  - [ ] Write failing tests for generator logic
  - [ ] Create `src/claude_code_hooks_daemon/daemon/playbook_generator.py`
  - [ ] Implement handler discovery (built-in + plugins)
  - [ ] Implement config-aware filtering (only enabled handlers)
  - [ ] Implement markdown generation matching current format
  - [ ] Verify 95%+ coverage
  - [ ] Run QA: `./scripts/qa/run_all.sh`
  - [ ] Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] Verify daemon status: RUNNING

### Phase 2: Sample Handler Migration (Validation)

Migrate 3 representative handlers to validate approach before full rollout:

- [ ] **Task 2.1**: DestructiveGitHandler (blocking, multiple patterns)
  - [ ] Write failing tests for `get_acceptance_tests()` implementation
  - [ ] Implement 7 test cases (one per destructive pattern):
    - [ ] git reset --hard
    - [ ] git clean -f
    - [ ] git push --force
    - [ ] git stash drop/clear
    - [ ] git checkout -- file
    - [ ] git restore file
  - [ ] Each test includes command, expected decision, message patterns, safety notes
  - [ ] Verify test definitions match existing playbook
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 2.2**: BritishEnglishHandler (advisory, non-terminal)
  - [ ] Write failing tests for advisory test definitions
  - [ ] Implement test case with `test_type=TestType.ADVISORY`
  - [ ] Expected decision: ALLOW with context message
  - [ ] Expected patterns: British spelling suggestions
  - [ ] Verify advisory behavior captured correctly
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 2.3**: SedBlockerHandler (complex matching logic)
  - [ ] Write failing tests for sed blocking scenarios
  - [ ] Implement test cases for:
    - [ ] Direct sed -i command (actual Bash tool)
    - [ ] sed in shell scripts
    - [ ] Safe cases that should NOT block
  - [ ] Setup commands to create test files
  - [ ] Cleanup commands to remove test files
  - [ ] Run QA: `./scripts/qa/run_all.sh`

### Phase 3: CLI Command (TDD)

- [ ] **Task 3.1**: Implement `generate-playbook` CLI command
  - [ ] Write failing tests for CLI command
  - [ ] Add `generate-playbook` subcommand to `cli.py`
  - [ ] Implement argparse integration
  - [ ] Add `--output PATH` flag (default: `CLAUDE/AcceptanceTests/PLAYBOOK-generated.md`)
  - [ ] Add `--include-disabled` flag (include all handlers, not just enabled)
  - [ ] Verify command execution
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 3.2**: Integration testing
  - [ ] Write integration test: generate playbook with sample handlers
  - [ ] Verify markdown output format matches current PLAYBOOK.md
  - [ ] Verify config-aware filtering (only enabled handlers)
  - [ ] Verify plugin handler inclusion (if plugins present)
  - [ ] Compare generated vs manual playbook structure
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 3.3**: Daemon restart verification (CRITICAL)
  - [ ] Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] Verify daemon status: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` (RUNNING)
  - [ ] Check logs for errors
  - [ ] Generate playbook: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook`
  - [ ] Verify output file created and formatted correctly

### Phase 4: Full Handler Migration (51 remaining handlers)

Migrate all remaining built-in handlers by category:

- [ ] **Task 4.1**: Safety handlers (10 handlers, priority 10-20)
  - [ ] pip_break_system (blocks --break-system-packages)
  - [ ] sudo_pip (blocks sudo pip)
  - [ ] curl_pipe_shell (blocks curl | bash)
  - [ ] dangerous_permissions (blocks chmod 777, etc.)
  - [ ] worktree_file_copy (blocks unsafe worktree ops)
  - [ ] pipe_blocker (blocks npm test | tail)
  - [ ] git_stash (advisory for git stash)
  - [ ] absolute_path (enforces absolute paths)
  - [ ] sed_blocker (already done in Phase 2)
  - [ ] destructive_git (already done in Phase 2)
  - [ ] Run QA after each migration
  - [ ] Verify daemon restarts successfully

- [ ] **Task 4.2**: QA enforcement handlers (5 handlers, priority 25-35)
  - [ ] tdd_enforcement (blocks handler creation without tests)
  - [ ] python_qa_suppression_blocker (blocks # type: ignore, # noqa)
  - [ ] php_qa_suppression_blocker (blocks @phpstan-ignore)
  - [ ] go_qa_suppression_blocker (blocks // nolint)
  - [ ] eslint_disable (blocks eslint-disable comments)
  - [ ] Run QA after each migration
  - [ ] Verify daemon restarts successfully

- [ ] **Task 4.3**: Workflow handlers (10 handlers, priority 40-55)
  - [ ] markdown_organization (enforces markdown location rules)
  - [ ] validate_plan_number (validates plan numbering)
  - [ ] plan_time_estimates (warns about time estimates)
  - [ ] plan_workflow (advisory for planning)
  - [ ] plan_number_helper (context for plan numbers)
  - [ ] npm_command (enforces npm conventions)
  - [ ] gh_issue_comments (blocks certain gh operations)
  - [ ] global_npm_advisor (warns about global npm)
  - [ ] web_search_year (suggests current year)
  - [ ] british_english (already done in Phase 2)
  - [ ] Run QA after each migration
  - [ ] Verify daemon restarts successfully

- [ ] **Task 4.4**: Post-event handlers (3 handlers)
  - [ ] bash_error_detector (PostToolUse - detects command errors)
  - [ ] validate_eslint_on_write (PostToolUse - runs eslint after write)
  - [ ] validate_sitemap (PostToolUse - validates sitemap structure)
  - [ ] Run QA after each migration
  - [ ] Verify daemon restarts successfully

- [ ] **Task 4.5**: Context injection handlers (5 handlers)
  - [ ] git_context_injector (UserPromptSubmit - adds git status)
  - [ ] workflow_state_restoration (SessionStart - restores workflow)
  - [ ] daemon_stats (StatusLine - shows daemon health)
  - [ ] git_branch (StatusLine - shows current branch)
  - [ ] model_context (StatusLine - shows model/context info)
  - [ ] Note: Some require non-triggerable events (use `requires_event` field)
  - [ ] Run QA after each migration
  - [ ] Verify daemon restarts successfully

- [ ] **Task 4.6**: Special event handlers (remaining)
  - [ ] SessionStart handlers (yolo_container_detection, suggest_statusline)
  - [ ] SessionEnd handlers (cleanup_handler)
  - [ ] PreCompact handlers (workflow_state_pre_compact, transcript_archiver)
  - [ ] Stop handlers (task_completion_checker, auto_continue_stop)
  - [ ] SubagentStop handlers (remind_validator, subagent_completion_logger, remind_prompt_library)
  - [ ] Notification handlers (notification_logger)
  - [ ] PermissionRequest handlers (auto_approve_reads)
  - [ ] Run QA after each migration
  - [ ] Verify daemon restarts successfully

### Phase 5: Documentation & Validation

- [ ] **Task 5.1**: Update handler development documentation
  - [ ] Add "Acceptance Testing" section to `CLAUDE/HANDLER_DEVELOPMENT.md`
  - [ ] Document `AcceptanceTest` dataclass structure
  - [ ] Provide complete examples (blocking, advisory, with setup)
  - [ ] Explain test_type enum values
  - [ ] Document best practices
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 5.2**: Create plugin migration guide
  - [ ] Create `CLAUDE/Plugin/ACCEPTANCE_TESTING.md`
  - [ ] Document how custom handlers should define tests
  - [ ] Provide plugin handler example
  - [ ] Explain automatic inclusion in generated playbook
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 5.3**: Update PLAYBOOK.md header
  - [ ] Add generation instructions to playbook header
  - [ ] Document `generate-playbook` command
  - [ ] Explain relationship between manual and generated playbooks
  - [ ] Keep FAIL-FAST instructions
  - [ ] Keep safety warnings
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 5.4**: Generate and validate official playbook
  - [ ] Run: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook`
  - [ ] Compare output with manual `PLAYBOOK.md`
  - [ ] Verify all 15+ test sections present
  - [ ] Verify safety warnings included
  - [ ] Verify FAIL-FAST instructions included
  - [ ] Verify format matches exactly
  - [ ] Document any discrepancies

- [ ] **Task 5.5**: Manual acceptance testing with generated playbook
  - [ ] Execute generated playbook manually (all tests)
  - [ ] Mark PASS/FAIL for each test
  - [ ] Document any failures
  - [ ] Fix issues using TDD (if found)
  - [ ] Re-run QA after fixes
  - [ ] Regenerate playbook
  - [ ] Verify all tests pass

### Phase 6: Plugin Support

- [ ] **Task 6.1**: Plugin acceptance test integration
  - [ ] Write tests for plugin handler discovery
  - [ ] Implement plugin test aggregation in PlaybookGenerator
  - [ ] Test with sample custom plugin handler
  - [ ] Verify custom handlers included in playbook
  - [ ] Verify tests execute correctly
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 6.2**: Plugin development guide updates
  - [ ] Update plugin template with `get_acceptance_tests()` example
  - [ ] Add acceptance testing to plugin development checklist
  - [ ] Document testing best practices for plugins
  - [ ] Provide working example plugin with tests
  - [ ] Run QA: `./scripts/qa/run_all.sh`

- [ ] **Task 6.3**: Final validation
  - [ ] Restart daemon successfully
  - [ ] Generate playbook with plugins
  - [ ] Verify plugin tests included
  - [ ] Execute full playbook (built-in + plugin tests)
  - [ ] All tests pass
  - [ ] Update GitHub issue #18 with completion summary
  - [ ] Close issue as completed

## Dependencies

- **Plan 00024**: Plugin System Fix (config loading must work for plugin integration)
- **Current Codebase**: Handler base class, HookResult, Decision enum
- **Testing Infrastructure**: pytest, 95% coverage requirement

## Technical Decisions

### Decision 1: Make get_acceptance_tests() Optional
**Context**: Need backward compatibility with existing handlers
**Options Considered**:
1. Make method required (forces all handlers to implement)
2. Make method optional with default implementation (backward compatible)

**Decision**: Option 2 - Optional method with default `return []`
**Rationale**:
- Allows gradual migration
- No breaking changes for existing handlers
- Handlers without tests simply won't appear in generated playbook
- Plugin handlers can adopt at their own pace
**Date**: 2026-02-02

### Decision 2: Playbook Format Must Match Exactly
**Context**: Need compatibility with existing manual acceptance testing workflow
**Options Considered**:
1. Create new format optimized for programmatic generation
2. Match existing PLAYBOOK.md format exactly

**Decision**: Option 2 - Match existing format
**Rationale**:
- Testers already familiar with format
- Can compare generated vs manual easily
- Transition is smoother
- Eventually replace manual with generated
**Date**: 2026-02-02

### Decision 3: Use Dataclass for Test Definitions
**Context**: Need type-safe, validated test structures
**Options Considered**:
1. Plain dictionaries (flexible but no validation)
2. Dataclass (type-safe, validated)
3. Custom class with methods (more complex)

**Decision**: Option 2 - Dataclass
**Rationale**:
- Type safety via type annotations
- Automatic validation
- IDE autocomplete support
- Simpler than custom classes
- Pythonic and widely understood
**Date**: 2026-02-02

## Success Criteria

- [ ] `AcceptanceTest` dataclass implemented with full validation
- [ ] Handler base class extended with `get_acceptance_tests()` (backward compatible)
- [ ] All 54 built-in handlers migrated with test definitions
- [ ] `generate-playbook` CLI command functional
- [ ] Generated playbook matches manual PLAYBOOK.md format exactly
- [ ] Plugin handlers automatically discovered and included
- [ ] All QA checks pass with 95%+ coverage
- [ ] Daemon loads successfully after all changes
- [ ] Manual playbook execution passes with generated playbook (all tests PASS)
- [ ] Documentation updated (HANDLER_DEVELOPMENT.md, plugin guide, PLAYBOOK.md header)
- [ ] GitHub issue #18 closed with completion summary

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Generated playbook format diverges from manual | Medium | Low | Strict format validation tests, side-by-side comparison |
| Handler test definitions incomplete/incorrect | High | Medium | Manual review during migration, execute generated playbook |
| Plugin compatibility issues | Medium | Low | Thorough plugin testing, backward compatibility design |
| Daemon fails to load after changes | High | Low | Daemon restart verification after each phase |
| Missing edge cases in test definitions | Medium | Medium | Compare with existing playbook, manual acceptance testing |

## Notes & Updates

### 2026-02-02 - Plan Created

Initial plan created based on user requirements for programmatic acceptance testing system.

**User Requirements**:
- Handlers implement interface to return acceptance test definitions
- Test objects have: title, command, description, should_block, expected_message_patterns
- Universal support (built-in + plugin handlers)
- CLI command to generate markdown playbook
- Config-aware (only enabled handlers)

**Key Design Decisions**:
1. Optional `get_acceptance_tests()` method (backward compatible)
2. `AcceptanceTest` dataclass with validation
3. Match existing PLAYBOOK.md format exactly
4. Support complex scenarios (setup/cleanup, non-triggerable events, advisory handlers)

**Next Steps**:
1. Begin Phase 1: Create dataclass and extend Handler base class
2. Validate approach with 3 sample handlers (Phase 2)
3. Implement CLI command (Phase 3)
4. Full migration of 54 handlers (Phase 4)

---

## Critical Files for Implementation

### New Files
- `/workspace/src/claude_code_hooks_daemon/core/acceptance_test.py` - AcceptanceTest dataclass and TestType enum
- `/workspace/src/claude_code_hooks_daemon/daemon/playbook_generator.py` - PlaybookGenerator class for markdown generation
- `/workspace/CLAUDE/Plugin/ACCEPTANCE_TESTING.md` - Plugin acceptance testing guide

### Modified Files
- `/workspace/src/claude_code_hooks_daemon/core/handler.py` - Add `get_acceptance_tests()` optional method
- `/workspace/src/claude_code_hooks_daemon/daemon/cli.py` - Add `generate-playbook` subcommand
- `/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py` - Example: First handler with test definitions
- `/workspace/CLAUDE/HANDLER_DEVELOPMENT.md` - Add acceptance testing documentation
- `/workspace/CLAUDE/AcceptanceTests/PLAYBOOK.md` - Update header with generation instructions

### Test Files
- `/workspace/tests/unit/core/test_acceptance_test.py` - Tests for AcceptanceTest dataclass
- `/workspace/tests/unit/core/test_handler.py` - Tests for Handler.get_acceptance_tests() (update existing)
- `/workspace/tests/unit/daemon/test_playbook_generator.py` - Tests for PlaybookGenerator
- `/workspace/tests/integration/test_generate_playbook_cli.py` - Integration tests for CLI command
- `/workspace/tests/integration/test_playbook_format.py` - Validate generated playbook format
