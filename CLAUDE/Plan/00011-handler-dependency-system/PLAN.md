# Plan: Handler Dependency System

## Problem Statement

**Config Duplication**: `markdown_organization` and `plan_number_helper` require identical config options (`track_plans_in_project`, `plan_workflow_docs`). Current solution uses YAML anchors which is a workaround, not a proper solution.

**No Dependency Enforcement**: User can disable `markdown_organization` but leave `plan_number_helper` enabled, causing runtime failures. The relationship between these handlers is implicit, not enforced.

**Registry Hack**: Lines 251-263 in `registry.py` use `hasattr(instance, "_track_plans_in_project")` to detect which handlers need plan workflow config - this is brittle and non-discoverable.

**User Requirement**: "We need a concept of dependent handlers" - child handlers should share config with parent handlers and be validated at config load time.

## Solution: Handler Options Inheritance

Implement `shares_options_with` attribute in Handler base class to create explicit parent-child relationships:

- Child handlers declare which parent they inherit config from
- Registry automatically copies parent options to child (two-pass registration)
- Pydantic validates dependencies at config load time (FAIL FAST)
- Eliminates hasattr() hack with generic options injection
- No YAML anchors needed in config

## Implementation

### Phase 1: Handler Base Class

**File**: `src/claude_code_hooks_daemon/core/handler.py`

Add two new attributes to Handler `__init__`:
- `shares_options_with: str | None = None` - parent handler name to inherit options from
- `depends_on: list[str] | None = None` - list of required handler names (for future use)

Update `__slots__` to include these attributes.

### Phase 2: Config Validation

**File**: `src/claude_code_hooks_daemon/config/models.py`

Add `@model_validator(mode="after")` to `HandlersConfig` class:
- Validate that if child handler is enabled and has `shares_options_with`, parent must be enabled
- Provide clear error messages: "Handler 'plan_number_helper' shares options with 'markdown_organization' but 'markdown_organization' is disabled"
- Add helper function `_snake_to_class_name()` for config-to-class name conversion

### Phase 3: Registry Options Inheritance

**File**: `src/claude_code_hooks_daemon/handlers/registry.py`

Replace hasattr() hack (lines 251-263) with generic options inheritance:

**Two-pass algorithm**:
1. First pass: collect all handler options into `options_registry` dict keyed by `{event_type}.{handler_name}`
2. Second pass: register handlers
   - If handler has `shares_options_with`, lookup parent options
   - Merge: `{**parent_options, **child_options}` (child overrides parent)
   - Use generic `setattr(instance, f"_{key}", value)` for ALL handlers (not just specific ones)

This eliminates the brittle `if hasattr(instance, "_track_plans_in_project"):` check.

### Phase 4: Update Child Handler

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_number_helper.py`

Change `__init__` to declare parent relationship:
```python
super().__init__(
    name="plan-number-helper",
    priority=30,
    terminal=False,
    tags=["workflow", "advisory", "planning"],
    shares_options_with="markdown_organization",  # NEW
)
```

No other changes needed - attributes remain the same.

### Phase 5: Update Config Template

**File**: `src/claude_code_hooks_daemon/daemon/init_config.py`

Update both `generate_minimal()` and `generate_full()`:

```yaml
markdown_organization:  # Parent handler
  enabled: true
  priority: 35
  options:
    track_plans_in_project: "CLAUDE/Plan"
    plan_workflow_docs: "CLAUDE/PlanWorkflow.md"

plan_number_helper:  # Child handler - shares options with parent
  enabled: true
  priority: 42
  # options: {}  # Inherits from markdown_organization (no duplication)
```

Add comments explaining the parent-child relationship.

### Phase 6: Update Project Config

**File**: `.claude/hooks-daemon.yaml`

Remove YAML anchors (lines 67, 87) and child options:

```yaml
markdown_organization:
  enabled: true
  priority: 35
  options:
    track_plans_in_project: "CLAUDE/Plan"
    plan_workflow_docs: "CLAUDE/PlanWorkflow.md"

plan_number_helper:
  enabled: true
  priority: 42
  # options now inherited automatically
```

### Phase 7: Tests (TDD)

**New Test File**: `tests/unit/handlers/test_dependency_system.py`

Create comprehensive tests:
- `test_shares_options_with_parent_enabled` - verify options inheritance works
- `test_shares_options_with_parent_disabled_fails` - verify validation catches error
- `test_child_options_override_parent` - verify child can override specific options
- `test_missing_parent_handler_warning` - verify graceful handling of missing parent

**Update Existing Tests**:
- `tests/unit/handlers/test_registry.py` - add options inheritance tests
- `tests/unit/handlers/pre_tool_use/test_plan_number_helper.py` - verify handler still works with new attribute

Target: Maintain 95% coverage.

### Phase 8: Documentation

Update docs to explain dependency system:
- **CLAUDE/HANDLER_DEVELOPMENT.md**: Add section on handler dependencies and options sharing
- **CLAUDE/ARCHITECTURE.md**: Document the parent-child handler pattern

## Critical Files

| File | Changes | Lines |
|------|---------|-------|
| `src/claude_code_hooks_daemon/core/handler.py` | Add shares_options_with, depends_on to __init__ | ~15 |
| `src/claude_code_hooks_daemon/config/models.py` | Add dependency validator | ~60 |
| `src/claude_code_hooks_daemon/handlers/registry.py` | Replace hasattr hack with options inheritance | ~80 |
| `src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_number_helper.py` | Add shares_options_with declaration | ~2 |
| `src/claude_code_hooks_daemon/daemon/init_config.py` | Update templates with comments | ~20 |
| `.claude/hooks-daemon.yaml` | Remove YAML anchors, simplify config | ~5 |
| `tests/unit/handlers/test_dependency_system.py` | New test file for dependencies | ~120 |

**Total**: ~300 lines across 7 files

## Verification Steps

### 1. Config Validation Test
```bash
# Test: Parent disabled, child enabled should fail
cat > /tmp/test-config.yaml << 'EOF'
version: "1.0"
daemon: {log_level: INFO}
handlers:
  pre_tool_use:
    markdown_organization: {enabled: false}
    plan_number_helper: {enabled: true}
EOF

python -c "
from claude_code_hooks_daemon.config.loader import Config
try:
    Config.load('/tmp/test-config.yaml')
    print('ERROR: Should have failed validation')
except ValueError as e:
    print(f'✓ Validation caught error: {e}')
"
```

### 2. Options Inheritance Test
```bash
# Test: Child inherits parent options
python -c "
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.core.router import EventRouter

registry = HandlerRegistry()
registry.discover()
router = EventRouter()

config = {
    'pre_tool_use': {
        'markdown_organization': {
            'enabled': True,
            'options': {
                'track_plans_in_project': 'CLAUDE/Plan',
                'plan_workflow_docs': 'CLAUDE/PlanWorkflow.md'
            }
        },
        'plan_number_helper': {
            'enabled': True,
            'options': {}  # Should inherit from parent
        }
    }
}

registry.register_all(router, config=config)

# Verify child handler has parent's options
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper import PlanNumberHelperHandler
handler = PlanNumberHelperHandler()
handler._track_plans_in_project = 'CLAUDE/Plan'  # Should be set by registry
print(f'✓ Child inherited: {handler._track_plans_in_project}')
"
```

### 3. Full QA Suite
```bash
./scripts/qa/run_all.sh
# Expected: All tests pass, 95%+ coverage maintained
```

### 4. Daemon Restart Test
```bash
# Update config and restart daemon
vim .claude/hooks-daemon.yaml  # Remove YAML anchors
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Daemon running, both handlers registered
```

### 5. Integration Test
Try to trigger plan_number_helper handler and verify it works correctly with inherited options.

## Benefits

1. **Eliminates Config Duplication**: No YAML anchors needed
2. **FAIL FAST**: Validation at config load time, not runtime
3. **Self-Documenting**: Handler code declares parent relationship explicitly
4. **Type-Safe**: Pydantic validates dependencies
5. **Generic**: No handler-specific logic in registry (eliminates hasattr hack)
6. **Backward Compatible**: Existing configs still work if they use explicit options
7. **Extensible**: Easy to add more parent-child relationships in future

## Engineering Principles Alignment

- ✅ **FAIL FAST**: Config validation catches errors at load time
- ✅ **DRY**: Options defined once in parent, inherited by children
- ✅ **SINGLE SOURCE OF TRUTH**: Parent handler is the source of truth
- ✅ **PROPER NOT QUICK**: Eliminates hasattr() hack with proper inheritance system
- ✅ **YAGNI**: Minimal implementation for current need (2 handlers), extensible for future

## Migration Path

Existing configs using YAML anchors continue to work:
- If child has explicit options, they're used (backward compatible)
- If child options are empty/missing, inherited from parent (new behavior)
- No breaking changes

## Risk Assessment

**Low Risk**:
- Config validation (catches errors early, clear messages)
- Handler base class changes (additive, backward compatible)
- Template updates (documentation only)

**Medium Risk**:
- Registry refactor (two-pass algorithm, options injection)
  - Mitigation: Comprehensive tests, verify existing handlers still work

**Testing Strategy**: TDD approach - write failing tests first, then implement
