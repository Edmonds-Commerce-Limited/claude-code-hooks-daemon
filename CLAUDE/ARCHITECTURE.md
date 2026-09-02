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
6. **Deterministic Only** - Daemon handles pattern matching; agent evaluation uses native Claude Code hooks

---

## When to Use Hooks Daemon vs Claude Code Native Hooks

**Critical Architectural Principle:** The hooks daemon is designed for **deterministic validation only**. Complex evaluation requiring reasoning should use **Claude Code's native agent-based hooks**.

### Use Hooks Daemon For (Deterministic)

✅ **Pattern matching and regex validation**

- Block dangerous commands: `sed -i`, `git reset --hard`, `rm -rf`
- Validate file paths (absolute vs relative)
- Check for QA suppression comments

✅ **Fast, synchronous validation**

- String contains/matches checks
- File extension validation
- Simple conditional logic

✅ **Reusable safety handlers**

- Apply same protection across multiple projects
- Configurable enable/disable per project
- Battle-tested patterns

**Examples:**

- `DestructiveGitHandler` - blocks `git reset --hard` via regex
- `SedBlockerHandler` - blocks `sed` command usage
- `AbsolutePathHandler` - validates file paths are absolute
- `PythonQaSuppessionBlocker` - detects `# noqa`, `# type: ignore`

### Use Claude Code Native Agent Hooks For (Complex Evaluation)

✅ **Workflow compliance validation**

- Verify release process is followed
- Check if planning workflow adhered to
- Validate architectural patterns

✅ **Context analysis requiring reasoning**

- Read session transcripts to detect agent context
- Analyse git state and commit history
- Evaluate whether changes align with project standards

✅ **Multi-turn investigation**

- Read multiple files to understand intent
- Execute commands to gather context
- Make judgment calls based on session history

**Examples:**

- Release workflow enforcement - verify `/release` skill was used
- Architecture compliance - check if changes follow documented patterns
- Planning workflow - ensure plan exists before implementation

### Configuration Locations

| Hook Type          | Configuration File          | Purpose                                       |
| ------------------ | --------------------------- | --------------------------------------------- |
| Daemon Handlers    | `.claude/hooks-daemon.yaml` | Deterministic validation, reusable handlers   |
| Native Agent Hooks | `.claude/settings.json`     | Complex evaluation, project-specific workflow |

**There is no `.claude/hooks.json`.** This table named one until Plan 00266
checked it against the Claude Code hook documentation: native hooks live in the
same `settings.json` files the daemon's own registrations use (`~/.claude/`,
`.claude/settings.json`, `.claude/settings.local.json`), plus skill and subagent
frontmatter. The `hooks/hooks.json` filename is real but belongs to PLUGINS,
which is the likely source of the error.

A native hook therefore sits **alongside** this daemon's `command` hook in the
same file, and both run: the documentation states that all matching hooks run
in parallel, so a slow `agent` hook does not serialise behind the daemon's
~1.8 ms dispatch.

**Parallel does not mean free.** The hooks do not compound — the cost is the
SLOWEST hook, not the sum — but the tool call still waits for that slowest
one. Adding a `prompt` hook to a `PreToolUse` event turns a ~45 ms round trip
into a multi-second one for that event, however fast the daemon is. Choose the
event accordingly: `Stop` and `SessionStart` already keep the user waiting,
whereas `PreToolUse` is the hot path this daemon exists to keep quick.

Note also that `reconcile_settings_hooks` is additive per EVENT, not per
entry — so add a native hook next to the daemon wrapper, never in place of it,
or the wrapper will not be restored.

### Example: Release Workflow Protection

**Wrong Approach** (Daemon Handler):

```python
# ❌ This requires analyzing session context and workflow state
class ReleaseWorkflowHandler(Handler):
    def handle(self, hook_input: dict) -> HookResult:
        # How do we know if release-agent is running?
        # How do we parse session transcript?
        # This is too complex for deterministic logic!
        pass
```

**Correct Approach** (Native Agent Hook in `.claude/settings.json`):

```json
{
  "PreToolUse": [{
    "matcher": {"tool": "Bash", "pattern": "git tag"},
    "hooks": [{
      "type": "agent",
      "prompt": "Read $TRANSCRIPT_PATH and verify release-agent is active. Block if not following @CLAUDE/development/RELEASING.md workflow."
    }]
  }]
}
```

### Decision Tree

```
Need to validate something?
│
├─ Is it a simple pattern match? (regex, string contains, etc.)
│  └─ YES → Use Hooks Daemon Handler
│
├─ Does it need to read files or analyze context?
│  └─ YES → Use Claude Code Native Agent Hook
│
├─ Does it require multi-turn reasoning?
│  └─ YES → Use Claude Code Native Agent Hook
│
└─ Does it need to work across multiple projects?
   └─ YES → Use Hooks Daemon Handler (if deterministic)
       └─ NO → Use Claude Code Native Agent Hook (if complex)
```

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
└─────────────┬───────────────────────────────┘
              │
  ┌───────────┼───────────────┐
  ▼           ▼               ▼
┌───────────┐ ┌─────────────┐ ┌──────────────────┐
│ Built-in  │ │   Plugin    │ │ Project Handlers │
│ Handlers  │ │  Handlers   │ │ (.claude/project │
│ (daemon)  │ │  (legacy)   │ │  -handlers/)     │
└───────────┘ └─────────────┘ └──────────────────┘
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
return HookResult(decision=Decision.ALLOW, context=accumulated_context)
```

`HookResult` is a Pydantic model with keyword-only fields — a positional
argument raises `TypeError`.

**Key Features**:

- **Terminal handlers**: Stop dispatch immediately (block/allow/ask)
- **Non-terminal handlers**: Provide guidance, allow fall-through
- **Priority-based**: Lower number runs first (5-60 range)
- **Fail-open**: Exceptions logged, execution continues

### 2. Handler Base Class (`core/handler.py`)

`Handler` is an ABC with **four** abstract methods. A subclass implementing
only `matches`/`handle` cannot be instantiated:
`TypeError: Can't instantiate abstract class ... with abstract methods get_acceptance_tests, get_claude_md`.

```python
class Handler(ABC):
    def __init__(
        self,
        handler_id: str | HandlerIDMeta | None = None,
        *,                             # everything below is keyword-only
        name: str | None = None,       # deprecated alias for handler_id
        priority: int = 50,
        terminal: bool = True,
        tags: list[str] | None = None,
        shares_options_with: str | None = None,
        depends_on: list[str] | None = None,
    ) -> None: ...

    @abstractmethod
    def matches(self, hook_input: dict) -> bool:
        """Return True if this handler should execute."""

    @abstractmethod
    def handle(self, hook_input: dict) -> HookResult:
        """Execute handler logic, return result."""

    @abstractmethod
    def get_claude_md(self) -> str | None:
        """Resident guidance for CLAUDE.md, or None if exempt."""

    @abstractmethod
    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Acceptance tests rendered into the release playbook."""
```

Either `handler_id` or `name` must be supplied — passing neither raises
`ValueError`.

**Handler Categories** (priority bands: see the
[Priority Guide](HANDLER_DEVELOPMENT.md#priority-guide), the single documented
statement of the ranges):

1. **Safety Handlers**

   - Block destructive operations
   - Prevent data loss
   - Terminal: Yes

2. **Code Quality Handlers**

   - QA suppression blockers
   - Lint enforcement
   - Terminal: Yes

3. **Workflow Handlers**

   - Enforce best practices
   - Provide guidance
   - Terminal: Configurable

4. **Advisory Handlers**

   - Warnings and suggestions
   - Terminal: Usually No

### 3. Hook Result (`core/hook_result.py`)

A `pydantic.BaseModel` with keyword-only fields. Note `context` is a **list**,
and an unrecognised keyword is silently DISCARDED rather than rejected — so a
typo here produces a handler that appears to work and does nothing.

```python
class HookResult(BaseModel):
    decision: Decision              # Decision.ALLOW / DENY / ASK
    reason: str | None = None       # Why blocked/asked
    context: list[str] = []         # Additional context for agent
    guidance: str | None = None     # Allow with feedback
    handlers_matched: list[str] = []
    worktree_path: str | None = None
    rule: str | None = None
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

### 5. Daemon Startup & Process Enforcement (`daemon/enforcement.py`)

**Single Daemon Process Enforcement**:

Prevents multiple daemon instances from running simultaneously. Behaviour varies by environment:

**Container Environments** (Docker, Podman, YOLO mode):

- System-wide enforcement: Only ONE daemon process allowed anywhere in the system
- Aggressive cleanup: Kills ALL other `claude_code_hooks_daemon` processes
- Safe assumption: Container is dedicated to one project
- Detection: Automatic via confidence scoring (>= 3 indicators)

**Non-Container Environments**:

- Conservative cleanup: Only removes stale PID files for current project
- No process killing: Multiple projects may have their own daemons
- Safety first: Don't interfere with other users/projects

**Process Termination**:

```python
# Graceful → Forceful escalation
process.terminate()  # SIGTERM
process.wait(timeout=2)  # 2-second grace period
# If still running:
process.kill()  # SIGKILL
```

**Configuration**:

```yaml
daemon:
  enforce_single_daemon_process: true  # Auto-enabled in containers during init
```

**When Enforcement Runs**:

- On daemon startup (`cmd_start()` in `cli.py`)
- Before checking if daemon already running
- Only if `enforce_single_daemon_process: true` in config

**Container Detection**:

- Uses confidence scoring from `utils/container_detection.py`
- Checks: `/.dockerenv`, cgroup paths, YOLO env vars, filesystem indicators
- Threshold: >= 3 indicators = container environment
- Auto-enables enforcement during config generation (`init_config.py`)

### 6. Plugin System (`plugins/loader.py`)

**Plugin Loading**:

```python
# Load from Python module path. PluginLoader.load_handler is a staticmethod,
# takes a Path (not a str), and returns a Handler INSTANCE (not a class).
handler = PluginLoader.load_handler(
    "npm_command_handler", Path(".claude/hooks/controller/handlers")
)

# Automatic case conversion
# npm_command_handler → NpmCommandHandler
# git_stash_handler → GitStashHandler
```

**Requirements**:

- Handler must inherit from `Handler` base class
- Module must export handler class
- Class name must follow PascalCase convention

### 6. Project Handler Loading (`handlers/project_loader.py`)

Project handlers provide convention-based auto-discovery from `.claude/project-handlers/`. They are the recommended approach for project-specific handlers, replacing the legacy plugin system for most use cases.

**Loading Pipeline** (in `DaemonController.initialise()`):

```
Phase 1: Built-in handlers (HandlerRegistry.discover + register_all)
Phase 2: Legacy plugins (PluginLoader.load_from_plugins_config)
Phase 3: Project handlers (ProjectHandlerLoader.discover_handlers)  ← NEW
```

**Discovery Mechanism**:

```python
ProjectHandlerLoader.discover_handlers(project_handlers_path)
```

1. Scans event-type subdirectories (`pre_tool_use/`, `post_tool_use/`, etc.)
2. Finds `.py` files, skipping files starting with `_` or `test_`
3. Uses `importlib.util.spec_from_file_location` to dynamically load each file
4. Finds concrete `Handler` subclasses in each module
5. Instantiates the handler and returns `(EventType, Handler)` tuples
6. Registers handlers with the `EventRouter`

**Directory Structure**:

```
.claude/project-handlers/
    conftest.py              # Shared test fixtures
    pre_tool_use/
        vendor_reminder.py   # Loaded → (PRE_TOOL_USE, handler)
        test_vendor_reminder.py  # Skipped (test_ prefix)
        _helpers.py              # Skipped (_ prefix)
    post_tool_use/
        build_checker.py     # Loaded → (POST_TOOL_USE, handler)
    session_start/
        branch_enforcer.py   # Loaded → (SESSION_START, handler)
```

**Configuration**:

```yaml
# .claude/hooks-daemon.yaml
project_handlers:
  enabled: true                       # Master switch (default: true)
  path: .claude/project-handlers      # Relative to workspace root
```

**Conflict Resolution**:

- If a project handler has the same `handler_id` as a built-in handler, the built-in handler takes precedence (logged as warning)
- Priority collisions use existing alphabetical-sorting tiebreaker in HandlerChain

**See [PROJECT_HANDLERS.md](PROJECT_HANDLERS.md) for complete developer guide.**

---

## Handler Library

### Built-in Handlers (Daemon Package)

| Handler              | Priority | Terminal | Purpose                                         |
| -------------------- | -------- | -------- | ----------------------------------------------- |
| `destructive_git`    | 10       | Yes      | Block `git reset --hard`, `git clean -f`, etc.  |
| `sed_blocker`        | 10       | Yes      | Block all sed usage (causes file corruption)    |
| `absolute_path`      | 12       | Yes      | Prevent container-specific paths in code        |
| `tdd_enforcement`    | 15       | Yes      | Require test file before handler implementation |
| `worktree_file_copy` | 15       | Yes      | Prevent copying files between worktrees         |
| `git_stash`          | 20       | Yes      | Block git stash creation (dangerous workflow)   |
| `qa_suppression`     | 30       | Yes      | Block QA suppression annotations (11 languages) |
| `web_search_year`    | 55       | Yes      | Ensure current year in search queries           |
| `british_english`    | 60       | No       | Warn about American spellings (non-blocking)    |

### Project-Specific Handlers (Plugins)

These remain in individual projects due to project-specific logic:

- **npm_command_handler** - Enforce llm: prefixed npm commands
- **ad_hoc_script_handler** - Prevent ad-hoc script execution
- **markdown_organization_handler** - Enforce documentation structure
- **plan_workflow_handler** - Plan creation guidance
- **official_plan_command_handler** - Enforce canonical plan discovery

---

## Priority Ranges

The priority bands are documented once, in the
[Priority Guide](HANDLER_DEVELOPMENT.md#priority-guide); the band boundaries
derive from `PriorityRange` in
`src/claude_code_hooks_daemon/constants/priority.py`.

**Why Priority Matters**:

1. **Safety First** - Destructive operations blocked before workflow checks
2. **Fail Fast** - Critical issues caught early in dispatch
3. **Efficiency** - Skip unnecessary checks after terminal handler matches

---

## Terminal vs Non-Terminal Handlers

### Terminal Handlers (default)

**Behaviour**:

- Stop dispatch immediately after execution
- Decision becomes final result (allow/deny/ask)
- Use for enforcement and blocking

**Example**:

```python
class DestructiveGitHandler(PreToolUseHandlerBase):
    def __init__(self):
        super().__init__(name="destructive-git", priority=10, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        return "git reset --hard" in get_bash_command(hook_input)

    def handle(self, hook_input: dict) -> GatingResult:
        return GatingResult(decision=Decision.DENY, reason="Destructive command blocked")
```

### Non-Terminal Handlers

**Behaviour**:

- Provide context/guidance but allow dispatch to continue
- Decision is ignored (treated as "allow")
- Context accumulated into final result
- Use for warnings, guidance, reminders

**Example**:

```python
class PlanWorkflowHandler(PreToolUseHandlerBase):
    def __init__(self):
        super().__init__(name="plan-workflow", priority=45, terminal=False)

    def matches(self, hook_input: dict) -> bool:
        return "CLAUDE/Plan/" in get_file_path(hook_input)

    def handle(self, hook_input: dict) -> GatingResult:
        return GatingResult(
            decision="allow",
            context="📋 Reminder: Follow PlanWorkflow.md conventions"
        )
```

---

## The Vendored Hooks Contract (Wire-Format Source of Truth)

**Claude Code's hooks documentation defines the wire format; the daemon
vendors it** (Plan 00271). `contracts/claude-code-hooks/` holds one tracked
JSON file per documented event — output fields, decision-token enums, blocking
mechanism, discarded fields, and a verbatim input example — plus `META.json`
(docs URL, fetch date, docs sha256, `last_audited_claude_code_version`) and
`ALLOWLIST.yaml` (reasoned, task-linked records of capabilities the daemon
deliberately does not express).

Three daemon sources of truth are diffed against the vendored contract on
every QA run by `scripts/qa/check_hook_contract.py` (`llm_qa.py hook_contract`,
network-free): `core/response_schemas.py`, `REFUSAL_CAPABLE_EVENTS` +
serialiser output in `core/hook_result.py`, and `can_block` in
`constants/events.py`. A stale allowlist entry fails the check, so recorded
gaps cannot rot. Freshness is separate: the `contract_staleness` SessionStart
advisory fires when the installed Claude Code version exceeds the last-audited
one, pointing at the refresh procedure in
`docs/guides/HOOK-CONTRACT-REFRESH.md` (raw-markdown fetch only — a
summarising fetch layer once fabricated a contract value). That procedure is
maintainer work on this repo, so a client install is given a client-shaped
remedy instead (upgrade, else report upstream) — see the handler's entry in
`docs/guides/HANDLER_REFERENCE.md`.

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

| Operation        | Time   | Notes                      |
| ---------------- | ------ | -------------------------- |
| Cold start       | ~50ms  | Config load + handler init |
| Warm dispatch    | ~20ms  | Cached handlers            |
| Handler match    | ~1-5ms | Per handler check          |
| Terminal handler | ~20ms  | Includes match + handle    |

**Compare to**:

- Standalone hooks: ~200ms (process spawn overhead)
- Multiple standalone hooks: 200ms × N (serial execution)

---

## Extension Points

### Adding Custom Handlers

1. **Create Handler Class**:

```python
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command

class CustomHandler(PreToolUseHandlerBase):
    def __init__(self):
        super().__init__(name="custom-handler", priority=50)

    def matches(self, hook_input: dict) -> bool:
        return "pattern" in get_bash_command(hook_input)

    def handle(self, hook_input: dict) -> GatingResult:
        return GatingResult(decision=Decision.DENY, reason="Blocked")
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

- **Handler Development**: See `HANDLER_DEVELOPMENT.md`
- **Debugging Hooks**: See `DEBUGGING_HOOKS.md`
- **Self-Install Mode**: See `SELF_INSTALL.md`
- **Release Process**: See `development/RELEASING.md`

---

**Maintained by**: Edmonds Commerce
**Last Updated**: 2025-01-16
**Version**: 1.0.0
