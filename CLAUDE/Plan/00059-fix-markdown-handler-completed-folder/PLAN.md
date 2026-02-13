# Plan 00059: Fix MarkdownOrganizationHandler to Allow Completed/ Folder Edits

**Status**: Not Started
**Created**: 2026-02-13
**Owner**: TBD
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (straightforward bug fix)

## Overview

The MarkdownOrganizationHandler currently blocks edits to `CLAUDE/Plan/Completed/NNNNN-*/PLAN.md` files because it validates folder names must start with numeric prefixes (e.g., `00051-description`). When it encounters `Completed/00051-*/`, it extracts "Completed" as the folder name and rejects it.

This bug was discovered during the February 2026 plan audit when attempting to update documentation in 5 completed plans that have unchecked task boxes.

**Blocking**: Cannot fix documentation in Plans 00048, 00049, 00050, 00051, 00052 until this is resolved.

## Goals

- Allow edits to `CLAUDE/Plan/Completed/NNNNN-*/PLAN.md` files
- Maintain validation for active plans in `CLAUDE/Plan/NNNNN-*/`
- Support other subdirectories (Archive/, Cancelled/) if they exist
- Fix without breaking existing validation logic

## Non-Goals

- Changing the overall plan structure
- Removing validation entirely
- Modifying plan numbering scheme

## Context & Background

### Current Handler Logic (lines 471-487)

```python
if normalized.lower().startswith("claude/plan/"):
    plan_match = re.match(r"^claude/plan/([^/]+)/", normalized, re.IGNORECASE)
    if plan_match:
        folder_name = plan_match.group(1)  # Extracts "Completed" or "00051-description"
        number_match = re.match(r"^(\d+)-", folder_name)
        if not number_match:
            return True  # BLOCKS - no numeric prefix
```

**Problem**: For path `CLAUDE/Plan/Completed/00051-critical-thinking/PLAN.md`, the regex extracts "Completed" as `folder_name`, which doesn't start with digits.

### Discovery Context

From Plan Audit Report (2026-02-13):
- 5 plans have complete work but unchecked task boxes
- Auditor-1 attempted to fix documentation but handler blocked edits
- All affected plans are in `Completed/` subfolder

## Tasks

### Phase 1: Analysis & Design

- [ ] **Read current handler implementation**
  - [ ] Locate MarkdownOrganizationHandler file
  - [ ] Read full validation logic
  - [ ] Identify exact blocking condition

- [ ] **Design fix approach**
  - [ ] Decide: special-case subdirectories or change pattern?
  - [ ] List known subdirectories: Completed/, Cancelled/, Archive/
  - [ ] Write test cases for fix validation

### Phase 2: TDD Implementation

- [ ] **Write failing tests**
  - [ ] Test: Allow edit to `CLAUDE/Plan/Completed/00051-*/PLAN.md`
  - [ ] Test: Allow edit to `CLAUDE/Plan/Cancelled/00012-*/PLAN.md`
  - [ ] Test: Still block `CLAUDE/Plan/InvalidFolder/file.md`
  - [ ] Test: Still validate active plans `CLAUDE/Plan/00059-*/PLAN.md`
  - [ ] Test: Block non-numeric active plans `CLAUDE/Plan/bad-name/PLAN.md`

- [ ] **Implement fix**
  - [ ] Add subdirectory allowlist or pattern adjustment
  - [ ] Update validation logic to handle nested paths
  - [ ] Ensure backward compatibility with active plan validation

- [ ] **Verify tests pass**
  - [ ] Run handler unit tests
  - [ ] Run full test suite
  - [ ] Check for regressions

### Phase 3: Integration & Verification

- [ ] **Update handler configuration**
  - [ ] Check if config changes needed
  - [ ] Update CLAUDE.md documentation if needed

- [ ] **Run full QA suite**: `./scripts/qa/llm_qa.py all`

- [ ] **Restart daemon**: Verify loads successfully
  - [ ] `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`

- [ ] **Live verification**
  - [ ] Attempt edit to `CLAUDE/Plan/Completed/00051-*/PLAN.md`
  - [ ] Verify edit is now allowed
  - [ ] Verify active plan validation still works

### Phase 4: Fix Affected Plans

- [ ] **Update Plan 00048** - Repository Cruft Cleanup
  - [ ] Change status to "Complete (2026-02-11)"
  - [ ] Mark all 11 tasks as [x]
  - [ ] Mark all 6 success criteria as [x]

- [ ] **Update Plan 00049** - NPM Handler LLM Detection
  - [ ] Mark all 22 subtasks as [x]
  - [ ] Mark all 10 success criteria as [x]

- [ ] **Update Plan 00050** - Handler Config Key Display
  - [ ] Mark all 19 subtasks as [x]
  - [ ] Mark all 9 success criteria as [x]

- [ ] **Update Plan 00051** - Critical Thinking Advisory
  - [ ] Change status to "Complete (2026-02-12)"
  - [ ] Mark all 19 tasks as [x]
  - [ ] Mark all 8 success criteria as [x]

- [ ] **Update Plan 00052** - LLM Command Wrapper Guide
  - [ ] Change status to "Complete (2026-02-12)"
  - [ ] Mark completed phase tasks as [x]
  - [ ] Leave future phase tasks as [ ] (deferred work)

- [ ] **Commit plan documentation updates**
  - [ ] Single commit with message: "Fix: Update documentation for completed plans 00048-00052"
  - [ ] Reference this plan and audit report in commit message

## Dependencies

- Audit Report: `/tmp/plan-audit-report-2026-02.md` (context on affected plans)
- Plans to fix: 00048, 00049, 00050, 00051, 00052

## Technical Decisions

### Decision 1: Subdirectory Allowlist vs Pattern Change

**Context**: How to allow `Completed/NNNNN-*/` while maintaining validation?

**Options Considered**:
1. **Subdirectory allowlist** - Check for known subdirs before validation
2. **Pattern change** - Extract second path segment for validation
3. **Disable validation** - Remove check entirely (rejected - loses safety)

**Decision**: TBD during implementation (likely Option 1 or 2)

**Rationale**:
- Option 1: Simple, explicit, easy to extend with new subdirs
- Option 2: More general, handles arbitrary nesting
- Option 3: Not acceptable - validation prevents accidental plan corruption

### Decision 2: Which Subdirectories to Support

**Known subdirectories**:
- `Completed/` - Current standard for finished plans
- `Cancelled/` - Mentioned in PlanWorkflow.md
- `Archive/` - Possible future use

**Decision**: Support all three initially

**Rationale**: Minimal cost to support all known subdirectories upfront rather than add them incrementally.

## Success Criteria

- [ ] Handler allows edits to `CLAUDE/Plan/Completed/NNNNN-*/PLAN.md`
- [ ] Handler allows edits to `CLAUDE/Plan/Cancelled/NNNNN-*/PLAN.md`
- [ ] Handler still blocks invalid active plan names (`CLAUDE/Plan/bad-name/`)
- [ ] Handler still validates active plans require numeric prefix
- [ ] All unit tests pass with 95%+ coverage
- [ ] Full QA suite passes
- [ ] Daemon loads successfully
- [ ] Live verification: Can edit completed plan PLAN.md files
- [ ] All 5 affected plans (00048-00052) updated with correct task marks

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Break active plan validation | High | Low | Comprehensive test coverage, test both paths |
| Miss edge cases in nesting | Medium | Medium | Test multiple nesting levels |
| Regex pattern too permissive | Medium | Low | Explicit subdirectory allowlist |

## Notes & Updates

### 2026-02-13
- Plan created based on February 2026 plan audit findings
- Handler bug discovered by auditor-1 when attempting documentation fixes
- Affects 5 completed plans that need task checkboxes updated
- Full context in `/tmp/plan-audit-report-2026-02.md`
