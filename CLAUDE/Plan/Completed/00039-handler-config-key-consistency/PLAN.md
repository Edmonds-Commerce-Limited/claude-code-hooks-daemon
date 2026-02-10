# Plan 00039: Handler Config Key Consistency

**Status**: Complete (2025-02-10)
**Created**: 2025-02-10
**Owner**: Claude
**Priority**: High
**Type**: Architecture Fix / Technical Debt
**Estimated Effort**: 3-4 hours

## Overview

Fix fundamental design flaw where HandlerID constants claim to be the "single source of truth" for handler config keys, but the handler registry silently ignores them and auto-generates keys from class names instead. This creates maintenance nightmares, hidden bugs, and violates DRY/SSOT principles.

## Goals

- Make HandlerID constants the actual single source of truth for config keys
- Eliminate auto-generation of config keys in registry
- Ensure registry uses HandlerID.*.config_key for all handler lookups
- Fix any mismatches between constants and current auto-generated keys
- Prevent future config key mismatches

## Non-Goals

- Changing handler class names
- Modifying handler functionality
- Refactoring unrelated registry code

## Context & Background

### The Problem

**Current Architecture**:
```python
# constants/handlers.py - Claims to be SSOT
SUGGEST_STATUSLINE = HandlerIDMeta(
    class_name="SuggestStatusLineHandler",
    config_key="suggest_statusline",  # ← NOT ACTUALLY USED
    display_name="suggest-statusline",
)

# handlers/registry.py - Actually determines config keys
def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    # SuggestStatusLineHandler → suggest_status_line
    # ← This is what's ACTUALLY used, ignoring the constant
```

**Result**: Config files must use `suggest_status_line` (auto-generated) even though the constant says `suggest_statusline`. The constant is ignored.

### Why It's Broken

1. **Violates Single Source of Truth**: HandlerID constants are supposed to be authoritative but aren't
2. **Hidden Bugs**: Mismatches cause "Unknown handler" errors that are hard to debug
3. **Maintenance Nightmare**: Developers must know to ignore the constants and use auto-generated keys
4. **No Validation**: If constant doesn't match auto-generated key, no warning/error occurs
5. **Misleading Documentation**: Constants claim to define config keys but don't

### Discovery

Found during release preparation when `suggest_statusline` config caused DEGRADED MODE:
- Config had `suggest_statusline` (matching constant)
- Daemon expected `suggest_status_line` (auto-generated)
- Error message: "Unknown handler 'suggest_statusline'. Did you mean: suggest_status_line"

## Tasks

### Phase 1: Analysis & Validation
- [x] ✅ **Audit all HandlerID constants vs auto-generated keys**
  - [x] ✅ Create script to compare HandlerID.*.config_key with _to_snake_case(class_name)
  - [x] ✅ Document all mismatches
  - [x] ✅ Identify which config key is "correct" (most widely used)

- [x] ✅ **Check existing configs for affected handlers**
  - [x] ✅ Scan `.claude/hooks-daemon.yaml`
  - [x] ✅ Scan `.claude/hooks-daemon.yaml.example`
  - [x] ✅ Scan `daemon/init_config.py`
  - [x] ✅ Document which keys are currently in use

### Phase 2: TDD - Write Failing Tests
- [x] ✅ **Create test file**: `tests/unit/handlers/test_config_key_consistency.py`
  - [x] ✅ Test: Registry uses HandlerID constants (not auto-generation)
  - [x] ✅ Test: _to_snake_case() matches all HandlerID.*.config_key values
  - [x] ✅ Test: Registry lookups use constant config_key
  - [x] ✅ Test: All handlers load successfully with constant-based keys

- [x] ✅ **Run tests - MUST FAIL**
  - [x] ✅ Verify tests fail with current auto-generation approach
  - [x] ✅ Document failure modes (5 mismatches found)

### Phase 3: Fix Registry to Use Constants
- [x] ✅ **Modify `handlers/registry.py`**
  - [x] ✅ Import HandlerID constants
  - [x] ✅ Create mapping: class_name → HandlerID constant
  - [x] ✅ Replace `_to_snake_case(attr.__name__)` with constant lookup
  - [x] ✅ Add validation: warn if constant doesn't exist for handler
  - [x] ✅ Keep `_to_snake_case()` as fallback with deprecation warning

- [x] ✅ **Update handler instantiation logic**
  - [x] ✅ Line 211: Use constant config_key instead of _to_snake_case()
  - [x] ✅ Line 267: Use constant config_key instead of _to_snake_case()
  - [x] ✅ Add error handling for missing constants

### Phase 4: Fix Mismatches
- [x] ✅ **Update HandlerID constants to match current reality**
  - [x] ✅ Change `suggest_statusline` → `suggest_status_line` in constant
  - [x] ✅ Fix any other mismatches found in Phase 1 (5 total)
  - [x] ✅ Update type literal in handlers.py

- [x] ✅ **Update configs to match constants**
  - [x] ✅ Decision: Update constants to match auto-generated (backward compatibility)
  - [x] ✅ Fix .claude/hooks-daemon.yaml.example
  - [x] ✅ Fix src/claude_code_hooks_daemon/daemon/init_config.py

### Phase 5: Validation & Testing
- [x] ✅ **Run failing tests - MUST NOW PASS**
  - [x] ✅ Verify registry uses constants
  - [x] ✅ Verify all handlers load correctly

- [x] ✅ **Integration testing**
  - [x] ✅ Restart daemon successfully
  - [x] ✅ Verify all handlers registered
  - [x] ✅ Check daemon logs for warnings/errors
  - [x] ✅ Test loading handlers from config

- [x] ✅ **Run audit - 0 mismatches found**

### Phase 6: Documentation
- [ ] ⬜ **Update architecture docs**
  - [ ] ⬜ Document how config keys are determined
  - [ ] ⬜ Explain HandlerID constant usage
  - [ ] ⬜ Update CLAUDE/ARCHITECTURE.md

- [ ] ⬜ **Update handler development guide**
  - [ ] ⬜ Document requirement to add HandlerID constant
  - [ ] ⬜ Explain config_key must match _to_snake_case(class_name)
  - [ ] ⬜ Add validation examples

## Technical Decisions

### Decision 1: Registry Lookup Strategy
**Context**: How should registry map config keys to handler classes?

**Options Considered**:
1. **Use HandlerID constants** (recommended)
   - Pros: True SSOT, explicit, validated, maintainable
   - Cons: Requires constant for every handler

2. **Auto-generate from class names**
   - Pros: No constants needed, automatic
   - Cons: Current approach, causes hidden bugs

3. **Hybrid: Constants with fallback**
   - Pros: Backward compatible, gradual migration
   - Cons: Two code paths, complexity

**Decision**: Use HandlerID constants with deprecation warning fallback
- Primary: Look up handler in HandlerID constants, use config_key
- Fallback: If no constant, auto-generate with loud warning
- Migration: All handlers eventually get constants

**Rationale**: This provides true SSOT while allowing gradual migration and catching missing constants early.

### Decision 2: Constant vs Config Direction
**Context**: When constant and auto-generated key mismatch, which is "correct"?

**Options Considered**:
1. **Constants are correct** - Update configs to match constants
   - Pros: Constants claim to be SSOT, cleaner keys
   - Cons: Breaks existing configs, requires migration

2. **Auto-generated is correct** - Update constants to match current reality
   - Pros: No config changes, backward compatible
   - Cons: Perpetuates auto-generation approach

**Decision**: Auto-generated is correct for now (update constants)
- Current configs already use auto-generated keys
- Changing configs would break all user installations
- Future: New handlers can use cleaner constant-based keys

**Rationale**: Backward compatibility and avoiding breaking changes for users.

### Decision 3: Validation Strategy
**Context**: How to catch mismatches between constants and auto-generated keys?

**Options Considered**:
1. **Runtime validation** - Warn on daemon startup if mismatch
2. **Test validation** - Unit test compares constants vs auto-generated
3. **CI validation** - GitHub Actions check enforces match
4. **All of the above**

**Decision**: All three approaches
- Unit test: `test_config_key_consistency.py` (catches in dev)
- Runtime warning: Registry logs warning on mismatch (catches in production)
- CI check: QA suite fails if mismatch (catches in PR)

**Rationale**: Defense in depth - catch early, catch often.

## Success Criteria

- [ ] Registry uses HandlerID constants for config key lookups
- [ ] All HandlerID.*.config_key values match auto-generated equivalents
- [ ] All handlers load successfully from config
- [ ] Daemon starts without warnings about missing/mismatched config keys
- [ ] Full QA suite passes
- [ ] Test coverage maintained at 95%+
- [ ] Documentation updated

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking existing configs | High | Low | Update constants to match current keys |
| Missing constants for handlers | Medium | Medium | Add fallback with deprecation warning |
| Circular import HandlerID → Registry | Medium | Low | Import only when needed, not at module level |
| Performance impact of constant lookup | Low | Low | Cache lookups, minimal overhead |

## Timeline

- Phase 1 (Analysis): 30 minutes
- Phase 2 (TDD): 45 minutes
- Phase 3 (Implementation): 1 hour
- Phase 4 (Fix Mismatches): 30 minutes
- Phase 5 (Testing): 45 minutes
- Phase 6 (Documentation): 30 minutes
- **Total**: ~4 hours

## Notes & Updates

### 2025-02-10 - Plan Created
- Identified during release preparation
- `suggest_statusline` constant didn't match `suggest_status_line` auto-generated key
- Caused DEGRADED MODE until configs were fixed
- Quick fix: Updated configs to match auto-generated keys
- Proper fix: This plan

## Related Work

- Related to handler development workflow (CLAUDE/HANDLER_DEVELOPMENT.md)
- Affects all 40+ handlers in the system
- Should be fixed before next major release
- Blocked by: None
- Blocks: None (but improves maintainability significantly)
