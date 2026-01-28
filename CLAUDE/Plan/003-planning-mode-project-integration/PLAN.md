# Plan 003: Claude Code Planning Mode → Project Workflow Integration

**Status**: Not Started
**Created**: 2026-01-28
**Owner**: AI Agent
**Priority**: High
**Estimated Effort**: 6-8 hours

## Overview

Bridge Claude Code's native planning mode to project-based plan tracking. When users enter planning mode, plans are automatically stored in the project repository following PlanWorkflow.md conventions, with auto-numbering and workflow guidance injection. This maintains the excellent planning mode UX while ensuring plans live in-project with proper versioning and structure.

Additionally, fix critical test coverage gaps in the markdown_organization handler that allowed the handler to be disabled in production without tests catching it.

## Goals

- Intercept Claude Code planning mode writes (`~/.claude/plans/*.md`) and redirect to project structure
- Auto-calculate next plan number by scanning project plan folders (including archive subdirs)
- Create properly numbered plan folders (5-digit padding: `00001-name/`)
- Write plan content to `PLAN.md` within plan folder
- Write stub redirect to original Claude Code location
- Inject workflow guidance when `plan_workflow_docs` configured
- Delegate folder renaming to Claude (use temp name initially)
- Fix markdown_organization handler test coverage gaps
- Add integration tests that verify handlers actually block in production

## Non-Goals

- Not changing Claude Code's planning mode UI
- Not automatically renaming plan folders (Claude does this)
- Not migrating existing Claude Code plans
- Not supporting custom plan number formats (5 digits is standard)

## Context & Background

### Current Problem

Claude Code's planning mode creates plans at `~/.claude/plans/{random-name}.md`:
- Plans stored outside project (not versioned)
- Random names don't follow conventions
- No integration with PlanWorkflow.md
- Users must manually copy/restructure plans

### Investigation Findings

During testing, the markdown_organization handler was disabled in config (`enabled: false`) but:
1. Unit tests passed (they bypass config loading)
2. No integration tests verify handlers are actually loaded in production
3. No tests verify handlers that claim to block actually prevent operations
4. Coverage metrics showed 95%+ but didn't catch this contract violation

**Root cause**: Tests verify handler logic in isolation but don't verify:
- Handler registration via config
- End-to-end blocking behavior through the full daemon stack
- Config-based enable/disable functionality

## Tasks

### Phase 1: Design & Configuration

- [ ] ⬜ **Design config schema for plan tracking**
  - [ ] ⬜ Add `track_plans_in_project` field (path string or null)
  - [ ] ⬜ Add optional `plan_workflow_docs` field
  - [ ] ⬜ Update config models with validation
  - [ ] ⬜ Update default config and schema
  - [ ] ⬜ Document config options in README

### Phase 2: Plan Number Calculation

- [x] ✅ **Implement plan number scanner**
  - [x] ✅ Write failing test: scan plan folder for highest number
  - [x] ✅ Write failing test: include subdirs (not starting with digits)
  - [x] ✅ Write failing test: exclude numbered subdirs (00001-name)
  - [x] ✅ Write failing test: handle empty plan folder
  - [x] ✅ Implement `get_next_plan_number(plan_folder: Path) -> str`
  - [x] ✅ Returns 5-digit zero-padded string (00001, 00002, etc.)
  - [x] ✅ Verify all tests pass

### Phase 3: Write Interception Logic

- [ ] ⬜ **Enhance markdown_organization handler**
  - [ ] ⬜ Write failing test: detect planning mode write pattern
  - [ ] ⬜ Write failing test: redirect write to project location
  - [ ] ⬜ Write failing test: create plan folder if missing
  - [ ] ⬜ Write failing test: write stub to original location
  - [ ] ⬜ Write failing test: handle folder collision (add -2 suffix)
  - [ ] ⬜ Implement write interception in `matches()`
  - [ ] ⬜ Implement write redirection in `handle()`
  - [ ] ⬜ Add collision detection and suffix logic
  - [ ] ⬜ Verify all tests pass

### Phase 4: Context & Guidance Generation

- [ ] ⬜ **Build response context for Claude**
  - [ ] ⬜ Write test: context includes new plan location
  - [ ] ⬜ Write test: context includes rename instruction
  - [ ] ⬜ Write test: context includes workflow docs reference (when configured)
  - [ ] ⬜ Write test: context warns on collision
  - [ ] ⬜ Implement context generation in HookResult
  - [ ] ⬜ Format as clear, actionable guidance
  - [ ] ⬜ Verify all tests pass

### Phase 5: Config Integration

- [ ] ⬜ **Wire up config to handler**
  - [ ] ⬜ Write test: feature disabled when track_plans_in_project is null
  - [ ] ⬜ Write test: feature disabled when track_plans_in_project is empty
  - [ ] ⬜ Write test: feature enabled with valid path
  - [ ] ⬜ Load config in handler __init__
  - [ ] ⬜ Add feature toggle checks
  - [ ] ⬜ Update handler registration to pass config
  - [ ] ⬜ Verify all tests pass

### Phase 6: Integration Testing (CRITICAL)

- [ ] ⬜ **Fix test coverage gaps**
  - [ ] ⬜ Create test: verify handlers load from config
  - [ ] ⬜ Create test: verify enabled=false prevents handler loading
  - [ ] ⬜ Create test: verify handler blocks through full daemon stack
  - [ ] ⬜ Create test: verify terminal handlers stop dispatch chain
  - [ ] ⬜ Create test: verify DENY returns to Claude Code correctly
  - [ ] ⬜ Add integration test: full planning mode flow end-to-end
  - [ ] ⬜ Add integration test: verify plan folder creation
  - [ ] ⬜ Add integration test: verify stub file creation
  - [ ] ⬜ Verify all tests pass

### Phase 7: Documentation & Examples

- [ ] ⬜ **Document new functionality**
  - [ ] ⬜ Update HANDLER_DEVELOPMENT.md with write interception pattern
  - [ ] ⬜ Add planning mode integration to README
  - [ ] ⬜ Document config options with examples
  - [ ] ⬜ Add troubleshooting section for common issues

### Phase 8: QA & Validation

- [ ] ⬜ **Full QA suite**
  - [ ] ⬜ Run all QA checks: `./scripts/qa/run_all.sh`
  - [ ] ⬜ Fix any linting issues
  - [ ] ⬜ Fix any type errors
  - [ ] ⬜ Verify 95%+ coverage maintained
  - [ ] ⬜ Manual test: enter planning mode, verify redirect
  - [ ] ⬜ Manual test: verify stub file works
  - [ ] ⬜ Manual test: verify workflow docs injection
  - [ ] ⬜ Manual test: verify collision handling
  - [ ] ⬜ Verify all checks pass

## Dependencies

- None (standalone feature)

## Technical Decisions

### Decision 1: Write Interception vs Guidance Only
**Context**: Should we intercept and modify the Write, or just provide guidance?

**Options Considered**:
1. **Intercept and handle write directly** - Handler creates files and returns ALLOW with context
2. **Block and provide guidance** - Handler returns DENY with instructions for Claude

**Decision**: Intercept and handle write directly (Option 1)

**Rationale**:
- Guarantees correct plan location (no reliance on Claude following instructions)
- Creates proper folder structure atomically
- Stub file ensures original location has redirect
- Claude gets clear context about what happened
- More reliable and less error-prone

**Date**: 2026-01-28

### Decision 2: Plan Numbering - 5 Digits with Zero Padding
**Context**: How many digits for plan numbers?

**Options Considered**:
1. 3 digits (001-999)
2. 5 digits (00001-99999)
3. Configurable width

**Decision**: 5 digits (Option 2)

**Rationale**:
- Supports 99,999 plans (more than sufficient)
- Consistent with archive systems
- Lexicographic sorting works correctly
- Not configurable to avoid complexity

**Date**: 2026-01-28

### Decision 3: Folder Naming - Delegate to Claude
**Context**: How to name plan folders?

**Options Considered**:
1. Parse first H1 heading from plan content
2. Prompt Claude for name before creating plan
3. Use temp name, instruct Claude to rename

**Decision**: Use temp name initially (Option 3)

**Rationale**:
- Simplest implementation (no parsing logic)
- No interruption to planning flow
- Claude sees content and can choose appropriate name
- Leverages Claude's understanding of plan content
- Follows existing random-name pattern temporarily

**Date**: 2026-01-28

### Decision 4: Test Coverage Strategy
**Context**: How to prevent the "handler disabled in config" bug from recurring?

**Options Considered**:
1. Only unit tests (current approach)
2. Add integration tests that load real config
3. Add end-to-end tests through full daemon stack

**Decision**: Add both integration and E2E tests (Options 2+3)

**Rationale**:
- Unit tests verify logic but not system behavior
- Integration tests verify config loading and handler registration
- E2E tests verify blocking actually works in production
- Test pyramid: many unit, some integration, few E2E
- Catches contract violations (claimed terminal but not blocking)

**Date**: 2026-01-28

## Success Criteria

- [ ] Planning mode writes redirect to project plan folder automatically
- [ ] Plan numbers auto-increment correctly (5-digit padding)
- [ ] Stub files created in original Claude Code location
- [ ] Workflow docs referenced when configured
- [ ] Collision handling works (suffix -2, -3, etc.)
- [ ] All QA checks pass (95%+ coverage, no type errors, no lint issues)
- [ ] Integration tests verify handlers load from config correctly
- [ ] Integration tests verify terminal handlers actually block operations
- [ ] Manual testing confirms full flow works end-to-end
- [ ] Documentation updated with new functionality

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Write interception changes break other Write handlers | High | Low | Comprehensive integration tests, verify priority ordering |
| Plan number collision in concurrent writes | Medium | Low | Use file system locks or atomic operations |
| Stub file overwrite existing content | High | Very Low | Check file existence, warn if present |
| Config schema changes break existing configs | Medium | Medium | Validate with default values, backward compatible |
| Testing gaps remain after fixes | High | Medium | Review with Opus agent, add contract tests |

## Timeline

- Phase 1-2: 1 hour (Design, plan numbering)
- Phase 3-4: 2 hours (Write interception, context generation)
- Phase 5: 1 hour (Config integration)
- Phase 6: 2 hours (Integration testing - CRITICAL)
- Phase 7: 30 minutes (Documentation)
- Phase 8: 1.5 hours (QA and validation)
- Target Completion: 2026-01-29

## Notes & Updates

### 2026-01-28 - Plan Created

Investigation revealed markdown_organization handler was disabled in production config but tests didn't catch it because:
- Unit tests bypass config loading
- No integration tests verify handler registration
- No E2E tests verify blocking behavior through full stack

This plan addresses both the new feature AND the test coverage gaps that allowed the bug to slip through.

**Key insight**: 95% line coverage doesn't equal 95% contract coverage. Need tests that verify handlers actually do what they claim (terminal=True means operations are blocked).

### Testing Philosophy

Following TDD strictly:
1. Write failing test that defines expected behavior
2. Implement minimum code to pass test
3. Refactor while keeping tests green
4. Run QA suite before each commit

Integration tests required for:
- Config-based feature toggles
- Handler registration and loading
- Terminal handler chain termination
- Full daemon request/response cycle

### 2026-01-28 - Phase 2 Complete: Plan Number Scanner

Implemented `get_next_plan_number()` utility following TDD:

**Implementation**: `src/claude_code_hooks_daemon/handlers/utils/plan_numbering.py`
- Scans plan folder for highest plan number
- Recursively scans non-numbered subdirectories (archive/, 2025/, etc.)
- Excludes numbered subdirectories from recursive scan (they are plan folders)
- Returns next number as 5-digit zero-padded string
- Full type annotations with Python 3.11+ syntax
- Comprehensive docstring with examples

**Tests**: `tests/unit/handlers/utils/test_plan_numbering.py`
- 16 comprehensive test cases covering:
  - Empty directory
  - Sequential and non-sequential numbering
  - Gaps in numbering
  - Subdirectory scanning (archive folders)
  - Edge cases (symlinks, broken symlinks, legacy 3-digit numbers)
  - Error handling (nonexistent directory)
  - Large plan numbers
- All tests passing
- Module achieves >95% coverage when run with full test suite

**Notes**:
- Implementation already existed but was verified to meet requirements
- Tests follow project patterns from existing utility tests
- Ready for use in Phase 3 (Write Interception Logic)
