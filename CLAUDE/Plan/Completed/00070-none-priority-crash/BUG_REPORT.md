# Hooks Daemon Bug Report: NoneType Priority Comparison

## Summary

The hooks daemon crashes with a `TypeError` when a handler in `.claude/hooks-daemon.yaml` has `enabled: true` but no `priority` field set. The daemon's handler chain sorting code attempts to compare `None < int`, which fails in Python 3.

## Error

```
TypeError: '<' not supported between instances of 'NoneType' and 'int'
```

Location: Handler priority sorting in the dispatch chain (likely `chain.py` or equivalent).

## Reproduction

1. Add a handler to `.claude/hooks-daemon.yaml` without a `priority` field:

```yaml
handlers:
  pre_tool_use:
    validate_instruction_content:
      enabled: true
      # priority: 50  <-- missing!
```

2. Start/restart the daemon
3. Daemon crashes during handler chain construction when it tries to sort handlers by priority

## Root Cause

The daemon reads handler configuration and constructs a priority-sorted chain. When a handler entry has `enabled: true` but no `priority` key, the priority value resolves to `None`. Python 3 does not support comparison between `NoneType` and `int`, so the sort operation raises `TypeError`.

## Expected Behaviour

The daemon should either:

1. **Require `priority`** - Validate config on load and raise a clear error message like: `"Handler 'validate_instruction_content' is enabled but has no priority set. Add 'priority: N' to the handler config."`
2. **Default to a sensible priority** - If `priority` is missing, default to a mid-range value (e.g., 50) and log a warning.

Option 1 (strict validation) is preferred as it makes configuration errors explicit rather than silently defaulting.

## Affected Version

The daemon version installed at the time of the bug (installed via git submodule at `.claude/hooks-daemon/`). The crash was observed on 2026-02-24.

## Workaround

Add an explicit `priority` field to every enabled handler in `.claude/hooks-daemon.yaml`:

```yaml
validate_instruction_content:
  enabled: true
  priority: 50  # <-- fix
```

This is what was applied to resolve the immediate issue in this project.

## Specific Config That Triggered It

The `validate_instruction_content` handler at line 84-85 of `.claude/hooks-daemon.yaml`:

```yaml
    validate_instruction_content:
      enabled: true
```

All other handlers in the config had explicit priority values. This single handler missing its priority caused the entire daemon to fail to start.

## Impact

- **All safety hooks disabled** - The daemon failing to start means no pre-tool-use blocking handlers run (destructive git protection, pipe blocker, etc.)
- **Silent failure** - The daemon crash is only apparent from hook feedback messages; it's easy to miss
- **Full restart required** - After fixing the config, the daemon needs a manual restart

## Suggested Fix (Upstream)

In the handler chain construction code (likely where handlers are sorted by priority):

```python
# Current (crashes):
sorted_handlers = sorted(handlers, key=lambda h: h.priority)

# Option A - Strict validation (preferred):
for handler in handlers:
    if handler.priority is None:
        raise ConfigurationError(
            f"Handler '{handler.name}' is enabled but has no priority set. "
            f"Add 'priority: N' to the handler config in .claude/hooks-daemon.yaml"
        )
sorted_handlers = sorted(handlers, key=lambda h: h.priority)

# Option B - Default with warning:
for handler in handlers:
    if handler.priority is None:
        logger.warning(
            f"Handler '{handler.name}' has no priority set, defaulting to 50"
        )
        handler.priority = 50
sorted_handlers = sorted(handlers, key=lambda h: h.priority)
```

Config schema validation should also be updated to require `priority` when `enabled: true`.
