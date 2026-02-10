# Project-Level Handlers - Developer Guide

**Audience**: LLM agents and human developers creating project-specific handlers
**Prerequisites**: hooks-daemon installed and running in the project

---

## Overview

Project-level handlers let you create custom hook handlers scoped to a specific project. They use the same `Handler` ABC as built-in handlers but live in your project repository, are auto-discovered by convention, and are version-controlled alongside your project code.

**Use project handlers for**:
- Project-specific workflow reminders (vendor commit workflow, asset rebuilds)
- Coding convention enforcement (branch naming, file pairing)
- Tool-specific reminders (run migrations after entity changes, regenerate API schemas)

**Use built-in handlers for**:
- Cross-project safety (destructive git, sed blocking)
- Language-agnostic quality enforcement

---

## Quick Start

### 1. Scaffold the Directory

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli init-project-handlers
```

This creates:

```
.claude/project-handlers/
    __init__.py
    conftest.py              # Shared pytest fixtures
    pre_tool_use/
        __init__.py
        example_handler.py   # Example to customise
        test_example_handler.py
```

### 2. Create a Handler

Create a Python file in the appropriate event-type subdirectory. The file name becomes the handler identity.

```python
# .claude/project-handlers/post_tool_use/migration_reminder.py
"""Migration reminder handler."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.utils import get_file_path


class MigrationReminderHandler(Handler):
    """Remind to create migrations after editing Entity classes."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="migration-reminder",
            priority=50,
            terminal=False,
            tags=["project", "database", "workflow"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match Write/Edit operations on Entity PHP files."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return False
        return "/src/Entity/" in file_path and file_path.endswith(".php")

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Provide reminder about database migrations."""
        return HookResult(
            decision=Decision.ALLOW,
            context=[
                "MIGRATION REMINDER:",
                "Entity modified. Remember to create/update migrations:",
                "  bin/console make:migration",
            ],
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Define acceptance tests for this handler."""
        return [
            AcceptanceTest(
                title="Entity edit triggers migration reminder",
                command='echo "Edit src/Entity/CustomerEntity.php"',
                description="Advisory reminder when editing Entity classes",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"MIGRATION REMINDER"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.ADVISORY,
                requires_event="PostToolUse after Write/Edit to Entity file",
            ),
        ]
```

### 3. Write a Test

Create a co-located test file with the `test_` prefix:

```python
# .claude/project-handlers/post_tool_use/test_migration_reminder.py
"""Tests for migration reminder handler."""

from migration_reminder import MigrationReminderHandler
from claude_code_hooks_daemon.core.hook_result import Decision


class TestMigrationReminderHandler:
    def setup_method(self) -> None:
        self.handler = MigrationReminderHandler()

    def test_init(self) -> None:
        assert self.handler.name == "migration-reminder"
        assert self.handler.priority == 50
        assert self.handler.terminal is False

    def test_matches_entity_write(self, write_hook_input) -> None:
        hook_input = write_hook_input("/var/www/project/src/Entity/Order.php")
        assert self.handler.matches(hook_input) is True

    def test_no_match_non_entity(self, write_hook_input) -> None:
        hook_input = write_hook_input("/var/www/project/src/Service/OrderService.php")
        assert self.handler.matches(hook_input) is False

    def test_handle_returns_advisory(self, write_hook_input) -> None:
        hook_input = write_hook_input("/var/www/project/src/Entity/Order.php")
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert any("MIGRATION REMINDER" in ctx for ctx in result.context)

    def test_acceptance_tests_defined(self) -> None:
        tests = self.handler.get_acceptance_tests()
        assert len(tests) >= 1
```

### 4. Run Tests

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers
# Or with verbose output:
$PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers --verbose
```

### 5. Validate

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers
```

### 6. Restart Daemon

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING
```

---

## Directory Structure

```
.claude/project-handlers/
    __init__.py              # Package marker
    conftest.py              # Shared pytest fixtures (bash_hook_input, etc.)
    .gitignore               # Exclude __pycache__/
    pre_tool_use/            # Handlers for PreToolUse events
        __init__.py
        vendor_changes_reminder.py
        test_vendor_changes_reminder.py
        composer_lock_sync.py
        test_composer_lock_sync.py
    post_tool_use/           # Handlers for PostToolUse events
        __init__.py
        build_asset_watcher.py
        test_build_asset_watcher.py
        migration_reminder.py
        test_migration_reminder.py
    session_start/           # Handlers for SessionStart events
        __init__.py
        branch_naming_enforcer.py
        test_branch_naming_enforcer.py
```

### Conventions

- **Event-type subdirectories** map handlers to events automatically. Place files in the correct subdirectory for the event you want to handle.
- **Files starting with `_`** are skipped (use for helpers: `_utils.py`).
- **Files starting with `test_`** are skipped during loading (they are test files).
- **One handler class per file** is recommended. If multiple `Handler` subclasses exist in one file, only the first is loaded (with a warning).
- **Tests co-located** with handler files for easy discovery and TDD.

### Valid Event-Type Directories

| Directory | Event | When It Fires |
|-----------|-------|---------------|
| `pre_tool_use/` | PreToolUse | Before a tool executes (Bash, Write, Edit, etc.) |
| `post_tool_use/` | PostToolUse | After a tool completes |
| `session_start/` | SessionStart | When a Claude Code session begins |
| `session_end/` | SessionEnd | When a session ends |
| `pre_compact/` | PreCompact | Before context compaction |
| `user_prompt_submit/` | UserPromptSubmit | When user submits a prompt |
| `permission_request/` | PermissionRequest | When a permission is requested |
| `notification/` | Notification | On notifications |
| `stop/` | Stop | When session stops |
| `subagent_stop/` | SubagentStop | When a subagent stops |

---

## Handler API Reference

### Handler Base Class

All project handlers must subclass `Handler` from `claude_code_hooks_daemon.core`:

```python
from claude_code_hooks_daemon.core import Handler
```

#### `__init__` Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `handler_id` | `str` | Yes | Unique identifier (kebab-case) |
| `priority` | `int` | No (default: 50) | Execution order (lower = earlier) |
| `terminal` | `bool` | No (default: True) | Stop dispatch after execution? |
| `tags` | `list[str]` | No (default: []) | Tags for categorisation/filtering |

#### Abstract Methods (must implement)

**`matches(self, hook_input: dict[str, Any]) -> bool`**
Return `True` if this handler should process the event. Called for every event of the handler's type.

**`handle(self, hook_input: dict[str, Any]) -> HookResult`**
Execute handler logic. Return a `HookResult` with a decision and optional context/reason.

**`get_acceptance_tests(self) -> list[AcceptanceTest]`**
Return at least one acceptance test definition. Used for playbook generation and validation.

#### Priority Ranges (Convention)

| Range | Category | Examples |
|-------|----------|---------|
| 0-19 | Safety | Destructive git blocker, sed blocker |
| 20-39 | Code quality | ESLint disable blocker, TDD enforcement |
| 40-59 | Workflow | Vendor reminders, migration reminders |
| 60-79 | Advisory | British English warnings, hints |
| 80-99 | Logging | Analytics, audit trails |

### HookResult

```python
from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.core.hook_result import Decision
```

| Decision | Behaviour | Use Case |
|----------|-----------|----------|
| `Decision.ALLOW` | Operation proceeds | Advisory reminders, context injection |
| `Decision.DENY` | Operation blocked | Safety enforcement, convention violation |
| `Decision.ASK` | User approval required | Risky but sometimes needed operations |

**Common patterns**:

```python
# Advisory (non-terminal) - context injected, operation continues
HookResult(decision=Decision.ALLOW, context=["REMINDER: Do X after Y"])

# Blocking (terminal) - operation denied
HookResult(decision=Decision.DENY, reason="Branch name does not match convention")

# Allow silently
HookResult.allow()

# Deny with reason
HookResult.deny(reason="Blocked because...")

# Allow with context
HookResult.allow(context=["INFO: Something to know"])
```

### Utility Functions

```python
from claude_code_hooks_daemon.core.utils import (
    get_bash_command,   # Extract command from Bash tool input
    get_file_path,      # Extract file path from Write/Edit tool input
    get_file_content,   # Extract content from Write tool input
)
```

### AcceptanceTest

```python
from claude_code_hooks_daemon.core import AcceptanceTest, TestType
```

Every handler must define at least one acceptance test. These are used to generate manual test playbooks.

```python
AcceptanceTest(
    title="Short description of the test",
    command='echo "safe command to test"',
    description="What this test verifies",
    expected_decision=Decision.ALLOW,  # or Decision.DENY
    expected_message_patterns=[r"regex.*pattern"],
    safety_notes="Uses echo - safe to execute",
    test_type=TestType.ADVISORY,  # or TestType.BLOCKING
    requires_event="PostToolUse after Write to Entity file",  # optional
)
```

---

## Terminal vs Non-Terminal

### Terminal Handlers (`terminal=True`, default)

- Stop the dispatch chain immediately when matched
- Decision becomes the final result (ALLOW/DENY/ASK)
- Use for **enforcement**: blocking operations, requiring approval

### Non-Terminal Handlers (`terminal=False`)

- Allow the dispatch chain to continue after execution
- Context is accumulated into the final result
- Use for **advisory**: reminders, warnings, context injection

**Recommendation**: Start with `terminal=False` (advisory) for project handlers. This is safer -- your handler provides guidance without blocking workflow. Upgrade to `terminal=True` only when blocking is needed.

---

## Testing

### conftest.py Fixtures

The scaffolded `conftest.py` provides factory fixtures:

```python
# bash_hook_input - creates Bash tool hook inputs
def test_matches_git_add(self, bash_hook_input):
    hook_input = bash_hook_input("git add vendor/package/file.php")
    assert self.handler.matches(hook_input) is True

# write_hook_input - creates Write tool hook inputs
def test_matches_entity_write(self, write_hook_input):
    hook_input = write_hook_input("/path/to/src/Entity/Order.php")
    assert self.handler.matches(hook_input) is True

# edit_hook_input - creates Edit tool hook inputs
def test_matches_edit(self, edit_hook_input):
    hook_input = edit_hook_input("/path/to/file.php", "old", "new")
    assert self.handler.matches(hook_input) is True
```

**Field names**: The daemon uses **snake_case** (`tool_name`, `tool_input`), not camelCase. The fixtures produce the correct format.

### Test Pattern

Every handler should test:

1. **Initialisation** - name, priority, terminal, tags
2. **matches() positive cases** - inputs that should trigger
3. **matches() negative cases** - inputs that should not trigger
4. **handle() result** - correct decision, context/reason content
5. **get_acceptance_tests()** - returns non-empty list

### Running Tests

```bash
# Via CLI command (recommended)
$PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers --verbose

# Or directly with pytest
$PYTHON -m pytest .claude/project-handlers/ --import-mode=importlib -v
```

---

## Configuration

### hooks-daemon.yaml

Project handlers are configured in the `project_handlers` section:

```yaml
# .claude/hooks-daemon.yaml
project_handlers:
  enabled: true                        # Master switch (default: true)
  path: .claude/project-handlers       # Path relative to workspace root
```

### Disabling a Specific Handler

Project handlers cannot be individually disabled via config (unlike built-in handlers). To disable a handler:

1. Rename the file to start with `_`: `vendor_changes_reminder.py` -> `_vendor_changes_reminder.py`
2. Or delete the file

### Disabling All Project Handlers

```yaml
project_handlers:
  enabled: false
```

---

## CLI Reference

All commands use the daemon's Python interpreter:

```bash
PYTHON=.claude/hooks-daemon/untracked/venv/bin/python
```

### init-project-handlers

Scaffold the project-handlers directory structure with example handler and conftest.py.

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli init-project-handlers [--force] [--project-root PATH]
```

| Flag | Description |
|------|-------------|
| `--force` | Overwrite existing directory |
| `--project-root` | Override auto-detected project root |

### validate-project-handlers

Discover and validate all project handlers without starting the daemon.

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers [--project-root PATH]
```

**Output includes**: handler name, priority, terminal flag, tags, acceptance test count, load status.

**Checks performed**:
- File can be imported
- Contains a concrete `Handler` subclass
- Handler can be instantiated
- `get_acceptance_tests()` returns non-empty list
- Reports count per event type

### test-project-handlers

Run pytest on project handler test files.

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers [--verbose] [--project-root PATH]
```

| Flag | Description |
|------|-------------|
| `--verbose` | Pass `-v` to pytest |
| `--project-root` | Override auto-detected project root |

### generate-playbook

Generate acceptance test playbook including project handler tests.

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook
```

Project handlers that define `get_acceptance_tests()` are automatically included in the generated playbook under a "Project Handlers" section.

---

## Common Patterns

### Pattern 1: Advisory Reminder (Non-Terminal)

Provide context without blocking. The most common project handler pattern.

```python
class ReminderHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            handler_id="my-reminder",
            priority=50,
            terminal=False,  # Advisory - don't block
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(
            decision=Decision.ALLOW,
            context=["REMINDER: Do something important after this operation."],
        )
```

### Pattern 2: Blocking Enforcer (Terminal)

Block operations that violate conventions.

```python
class EnforcerHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            handler_id="my-enforcer",
            priority=30,
            terminal=True,  # Blocking
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        if self._is_valid():
            return HookResult.allow()
        return HookResult.deny(reason="Convention violated: ...")
```

### Pattern 3: File Path Matching (PostToolUse)

React to writes/edits to specific file paths.

```python
def matches(self, hook_input: dict[str, Any]) -> bool:
    file_path = get_file_path(hook_input)
    if not file_path:
        return False
    return "/src/Entity/" in file_path and file_path.endswith(".php")
```

### Pattern 4: Bash Command Matching (PreToolUse)

Intercept specific shell commands.

```python
def matches(self, hook_input: dict[str, Any]) -> bool:
    command = get_bash_command(hook_input)
    if not command:
        return False
    return bool(re.search(r"\bgit\s+(add|commit)\b", command)) and "vendor/" in command
```

### Pattern 5: SessionStart Check

Run a check when a session begins (e.g., branch naming).

```python
class SessionCheckHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            handler_id="session-check",
            priority=30,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True  # Always match on session start

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        # Run check (e.g., subprocess to get branch name)
        # Return allow/deny based on result
        ...
```

---

## Troubleshooting

### Handler not loading

1. **Check file location**: Handler must be in a valid event-type subdirectory
2. **Check file name**: Must not start with `_` or `test_`
3. **Check imports**: Run `validate-project-handlers` for import errors
4. **Check class**: Must be a concrete subclass of `Handler` (not abstract)
5. **Restart daemon**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

### Tests failing to import

- Ensure `conftest.py` exists at `.claude/project-handlers/conftest.py`
- The conftest adds event-type subdirectories to `sys.path`
- Use `--import-mode=importlib` when running pytest directly
- Import handlers by module name (e.g., `from migration_reminder import MigrationReminderHandler`)

### Handler not triggering

1. **Check event type**: Is the handler in the correct subdirectory for the event?
2. **Check `matches()`**: Is the matching logic correct? Test with `validate-project-handlers`.
3. **Check daemon logs**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli logs`
4. **Check priority**: A higher-priority terminal handler may be stopping dispatch before yours runs.

### Field name issues

The daemon's internal protocol uses **snake_case**:
- `tool_name` (not `toolName`)
- `tool_input` (not `toolInput`)

Use the utility functions (`get_bash_command`, `get_file_path`) which handle this correctly.

### Daemon won't start after adding handler

1. Check for syntax errors in your handler file
2. Check for import errors: `$PYTHON -c "import your_handler_module"`
3. Run `validate-project-handlers` for detailed error output
4. Check daemon logs for the specific error

---

## Differences from Built-in Handlers

| Aspect | Built-in Handlers | Project Handlers |
|--------|-------------------|------------------|
| Location | `src/claude_code_hooks_daemon/handlers/` | `.claude/project-handlers/` |
| Discovery | `pkgutil.walk_packages` | `importlib.util.spec_from_file_location` |
| IDs | `HandlerID` constants | String `handler_id` |
| Config | Per-handler enable/disable in YAML | Master switch + file naming |
| Scope | Cross-project, reusable | Project-specific |
| Tests | Separate `tests/` directory | Co-located `test_` files |
| Priority conflicts | Built-in handlers win | Warning logged |
| Python env | Daemon package | Daemon venv (same Python) |

---

## See Also

- [HANDLER_DEVELOPMENT.md](HANDLER_DEVELOPMENT.md) - Full handler development guide
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture and loading pipeline
- [DEBUGGING_HOOKS.md](DEBUGGING_HOOKS.md) - Debug hook events before writing handlers
