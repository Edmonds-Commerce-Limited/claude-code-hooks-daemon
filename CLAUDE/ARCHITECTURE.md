# Claude Code Hooks Daemon - Architecture

**Version 1.0** | **Status**: Active Development

---

## Overview

Claude Code Hooks Daemon is a reusable, configurable hook system for Claude Code that provides battle-tested safety handlers and workflow enforcement across multiple projects.

### Key Principles

1. **Reusability** - Write once, use everywhere
2. **Configurability** - Enable/disable handlers per project
3. **Extensibility** - Easy plugin system for custom handlers
4. **Performance** - Single process, efficient dispatch (20ms vs 200ms)
5. **Safety** - Fail-open philosophy (errors don't block work)

---

## Architecture Layers

```
┌─────────────────────────────────────────────┐
│         Claude Code Tool Execution          │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│         Hook Entry Point (pre_tool_use.py)  │
│  - Load configuration from hooks-daemon.yaml│
│  - Initialize Front Controller               │
│  - Register handlers based on config        │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│            Front Controller Engine           │
│  - Sort handlers by priority (low → high)   │
│  - Match handlers against hook input        │
│  - Dispatch to terminal or non-terminal     │
│  - Accumulate context from non-terminal     │
│  - Return first terminal decision or allow  │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│             Handler Base Class               │
│  - matches(hook_input) → bool               │
│  - handle(hook_input) → HookResult          │
│  - Properties: name, priority, terminal     │
└─────────────────────┬───────────────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
┌───────────────────┐   ┌──────────────────────┐
│  Built-in Handlers│   │  Plugin Handlers     │
│  (daemon package) │   │  (project-specific)  │
└───────────────────┘   └──────────────────────┘
```

---

## Core Components

### 1. Front Controller (`core/front_controller.py`)

**Responsibilities**:
- Register handlers and sort by priority
- Read hook input from stdin (JSON)
- Dispatch to matching handlers
- Handle terminal vs non-terminal execution
- Accumulate context from non-terminal handlers
- Write JSON output to stdout
- Log errors without blocking execution

**Dispatch Algorithm**:

```python
for handler in sorted_handlers:
    if handler.matches(hook_input):
        result = handler.handle(hook_input)

        if handler.terminal:
            # Stop dispatch, return result
            return result
        else:
            # Accumulate context, continue
            accumulated_context.append(result.context)
            continue

# No terminal handler matched
return HookResult("allow", context=accumulated_context)
```

**Key Features**:
- **Terminal handlers**: Stop dispatch immediately (block/allow/ask)
- **Non-terminal handlers**: Provide guidance, allow fall-through
- **Priority-based**: Lower number runs first (5-60 range)
- **Fail-open**: Exceptions logged, execution continues

### 2. Handler Base Class (`core/handler.py`)

```python
class Handler:
    def __init__(self, name: str, priority: int = 100, terminal: bool = True):
        self.name = name
        self.priority = priority
        self.terminal = terminal

    def matches(self, hook_input: dict) -> bool:
        """Return True if this handler should execute."""
        raise NotImplementedError

    def handle(self, hook_input: dict) -> HookResult:
        """Execute handler logic, return result."""
        raise NotImplementedError
```

**Handler Categories**:

1. **Safety Handlers** (priority 10-20)
   - Block destructive operations
   - Prevent data loss
   - Terminal: Yes

2. **Workflow Handlers** (priority 25-45)
   - Enforce best practices
   - Provide guidance
   - Terminal: Configurable

3. **Quality Handlers** (priority 50-60)
   - Check code quality
   - Warn about issues
   - Terminal: Usually No

### 3. Hook Result (`core/hook_result.py`)

```python
class HookResult:
    def __init__(
        self,
        decision: str = "allow",      # "allow", "deny", "ask"
        reason: Optional[str] = None,  # Why blocked/asked
        context: Optional[str] = None, # Additional context for agent
        guidance: Optional[str] = None # Allow with feedback
    ):
        ...
```

**Decision Types**:
- **allow**: Operation proceeds (silent or with context/guidance)
- **deny**: Operation blocked (must provide reason)
- **ask**: User approval required (must provide reason)

### 4. Configuration System (`config/`)

**File Discovery** (in order):
1. `.claude/hooks-daemon.yaml` (project root)
2. `.claude/hooks-daemon.json` (alternative format)
3. `~/.config/claude-code/hooks-daemon.yaml` (user global)
4. `/etc/claude-code/hooks-daemon.yaml` (system global)

**Configuration Schema**:

```yaml
version: 1.0

settings:
  logging_level: INFO
  log_file: .claude/hooks/daemon.log
  fail_mode: open  # open or closed

handlers:
  pre_tool_use:
    # Built-in handlers (from daemon package)
    destructive_git:
      enabled: true
      priority: 10  # Override default

    git_stash:
      enabled: true
      priority: 20
      escape_hatch: "I HAVE CONFIRMED STASH IS ONLY OPTION"

    # ... more handlers

plugins:
  # Project-specific handlers
  - path: .claude/hooks/controller/handlers
    handlers:
      - npm_command_handler  # snake_case → NpmCommandHandler
      - markdown_organization_handler
```

**Configuration Loading**:
1. Find config file (search paths)
2. Parse YAML/JSON
3. Validate against schema (jsonschema)
4. Merge with defaults
5. Instantiate and register handlers

### 5. Plugin System (`plugins/loader.py`)

**Plugin Loading**:

```python
# Load from Python module path
handler_class = load_handler("npm_command_handler", ".claude/hooks/controller/handlers")

# Automatic case conversion
# npm_command_handler → NpmCommandHandler
# git_stash_handler → GitStashHandler
```

**Requirements**:
- Handler must inherit from `Handler` base class
- Module must export handler class
- Class name must follow PascalCase convention

---

## Handler Library

### Built-in Handlers (Daemon Package)

| Handler | Priority | Terminal | Purpose |
|---------|----------|----------|---------|
| `destructive_git` | 10 | Yes | Block `git reset --hard`, `git clean -f`, etc. |
| `sed_blocker` | 10 | Yes | Block all sed usage (causes file corruption) |
| `absolute_path` | 12 | Yes | Prevent container-specific paths in code |
| `tdd_enforcement` | 15 | Yes | Require test file before handler implementation |
| `worktree_file_copy` | 15 | Yes | Prevent copying files between worktrees |
| `git_stash` | 20 | Yes | Block git stash creation (dangerous workflow) |
| `eslint_disable` | 30 | Yes | Block ESLint suppression comments |
| `web_search_year` | 55 | Yes | Ensure current year in search queries |
| `british_english` | 60 | No | Warn about American spellings (non-blocking) |

### Project-Specific Handlers (Plugins)

These remain in individual projects due to project-specific logic:

- **npm_command_handler** - Enforce llm: prefixed npm commands
- **ad_hoc_script_handler** - Prevent ad-hoc script execution
- **markdown_organization_handler** - Enforce documentation structure
- **plan_workflow_handler** - Plan creation guidance
- **official_plan_command_handler** - Enforce canonical plan discovery
- **validate_plan_number_handler** - Validate plan numbering

---

## Priority Ranges

**Recommended Priority Allocation**:

```
5-9:   Architecture enforcement (controller pattern, etc.)
10-20: Safety (destructive operations, data loss prevention)
21-30: Code quality (ESLint, TypeScript, formatting)
31-45: Workflow enforcement (TDD, planning, documentation)
46-60: Advisory (warnings, suggestions, non-blocking)
```

**Why Priority Matters**:

1. **Safety First** - Destructive operations blocked before workflow checks
2. **Fail Fast** - Critical issues caught early in dispatch
3. **Efficiency** - Skip unnecessary checks after terminal handler matches

---

## Terminal vs Non-Terminal Handlers

### Terminal Handlers (default)

**Behavior**:
- Stop dispatch immediately after execution
- Decision becomes final result (allow/deny/ask)
- Use for enforcement and blocking

**Example**:

```python
class DestructiveGitHandler(Handler):
    def __init__(self):
        super().__init__(name="destructive-git", priority=10, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        return "git reset --hard" in get_bash_command(hook_input)

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="deny", reason="Destructive command blocked")
```

### Non-Terminal Handlers

**Behavior**:
- Provide context/guidance but allow dispatch to continue
- Decision is ignored (treated as "allow")
- Context accumulated into final result
- Use for warnings, guidance, reminders

**Example**:

```python
class PlanWorkflowHandler(Handler):
    def __init__(self):
        super().__init__(name="plan-workflow", priority=45, terminal=False)

    def matches(self, hook_input: dict) -> bool:
        return "CLAUDE/Plan/" in get_file_path(hook_input)

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(
            decision="allow",
            context="📋 Reminder: Follow PlanWorkflow.md conventions"
        )
```

---

## Error Handling & Fail-Open Philosophy

**Core Principle**: **Never block work due to hook system failures**

### Error Scenarios

1. **Configuration errors** - Use defaults, log warning
2. **Handler instantiation errors** - Skip handler, log error
3. **Handler execution errors** - Return allow, log error
4. **JSON parsing errors** - Return allow, log error

### Error Logging

```python
# Errors logged to untracked/hook-errors.log
# Format: [timestamp] [event] [handler] ERROR: message
# Example:
[2025-01-16 13:00:00] [PreToolUse] [destructive-git] ERROR: regex compilation failed
```

### Why Fail-Open?

1. **Development Velocity** - Hook bugs don't halt development
2. **Debugging** - Errors logged, can be reviewed later
3. **Graceful Degradation** - Partial hook system better than none
4. **User Control** - Users can fix config without being blocked

---

## Performance Considerations

### Optimization Strategies

1. **Single Process** - No subprocess spawning (200ms → 20ms)
2. **Lazy Loading** - Handlers loaded only when enabled
3. **Early Exit** - Terminal handlers stop dispatch immediately
4. **Regex Compilation** - Compile patterns in `__init__`
5. **Minimal I/O** - Read stdin once, write stdout once

### Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| Cold start | ~50ms | Config load + handler init |
| Warm dispatch | ~20ms | Cached handlers |
| Handler match | ~1-5ms | Per handler check |
| Terminal handler | ~20ms | Includes match + handle |

**Compare to**:
- Standalone hooks: ~200ms (process spawn overhead)
- Multiple standalone hooks: 200ms × N (serial execution)

---

## Extension Points

### Adding Custom Handlers

1. **Create Handler Class**:

```python
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command

class CustomHandler(Handler):
    def __init__(self):
        super().__init__(name="custom-handler", priority=50)

    def matches(self, hook_input: dict) -> bool:
        return "pattern" in get_bash_command(hook_input)

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="deny", reason="Blocked")
```

2. **Register via Configuration**:

```yaml
plugins:
  - path: .claude/hooks/custom
    handlers:
      - custom_handler
```

### Creating Handler Packages

```python
# my_handlers/destructive_ops.py
from claude_code_hooks_daemon.core import Handler, HookResult

class MyCustomHandler(Handler):
    ...

# Install as package
pip install my-claude-handlers

# Use in config
plugins:
  - module: my_claude_handlers
    handlers:
      - my_custom_handler
```

---

## Security Considerations

### Input Validation

- All hook input from stdin treated as untrusted
- JSON parsing with error handling
- No code execution from hook input
- File paths sanitized (no directory traversal)

### Handler Isolation

- Handlers cannot modify each other's state
- Handler errors don't affect other handlers
- Each handler runs in same process (shared memory intentional)

### Configuration Security

- Config files validated against schema
- Malformed config rejected (use defaults)
- No arbitrary code execution from config
- Plugin paths restricted to project directory

---

## Testing Strategy

### Unit Tests (`tests/unit/`)

- Test each handler in isolation
- Mock hook_input fixtures
- Verify matches() and handle() logic
- Test edge cases and error conditions

### Integration Tests (`tests/integration/`)

- Test full dispatch cycle
- Test configuration loading
- Test plugin system
- Test multiple handlers interacting

### Coverage Requirements

- **Core**: 100% coverage
- **Handlers**: 95%+ coverage
- **Config**: 100% coverage
- **Overall**: 95%+ minimum

---

## Future Enhancements

### v1.1 Roadmap

- [ ] Hot-reload configuration without restart
- [ ] Metrics and monitoring (handler execution time, match rate)
- [ ] Handler marketplace/registry
- [ ] Advanced configuration (per-file handler overrides)
- [ ] Handler dependencies (handler A requires handler B)

### v2.0 Vision

- [ ] Multi-event coordination (PreToolUse → PostToolUse chains)
- [ ] Async handler support (I/O-bound handlers)
- [ ] Handler versioning and compatibility
- [ ] Web UI for configuration and monitoring
- [ ] Handler analytics (most triggered, most blocking)

---

## References

- **Handler Development**: See `handler_development.md`
- **Configuration Guide**: See `configuration.md`
- **Migration Guide**: See `migration_guide.md`
- **API Reference**: See `api.md` (coming soon)

---

**Maintained by**: Edmonds Commerce
**Last Updated**: 2025-01-16
**Version**: 1.0.0
