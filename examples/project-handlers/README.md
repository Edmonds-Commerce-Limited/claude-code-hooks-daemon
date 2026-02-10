# Example Project Handlers

These examples demonstrate common project handler patterns. Copy and adapt them for your own project.

## Examples

### 1. Vendor Changes Reminder (PreToolUse, Advisory)

**File**: `pre_tool_use/vendor_changes_reminder.py`

Detects `git add`/`git commit` commands that include vendor paths and provides an advisory reminder about the first-party vendor commit workflow. Non-terminal (advisory only).

**Pattern**: Bash command matching with regex, advisory context injection.

### 2. Branch Naming Enforcer (SessionStart, Blocking)

**File**: `session_start/branch_naming_enforcer.py`

Checks the current git branch name against allowed patterns at session start. Denies sessions on branches that do not follow naming conventions. Terminal (blocking).

**Pattern**: SessionStart check with subprocess, blocking enforcement.

### 3. Build Asset Watcher (PostToolUse, Advisory)

**File**: `post_tool_use/build_asset_watcher.py`

Detects writes to TypeScript/SCSS source files and reminds to rebuild compiled assets. Non-terminal (advisory only).

**Pattern**: File path matching on PostToolUse events, advisory context injection.

## How to Use

1. Copy the example handler and test file to your `.claude/project-handlers/` directory
2. Adapt the matching logic, handler ID, and context messages to your project
3. Run tests: `$PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers --verbose`
4. Validate: `$PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers`
5. Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

## Handler Anatomy

Every project handler follows this structure:

```python
from typing import Any
from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision

class MyHandler(Handler):
    """Docstring explaining what this handler does."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="my-handler-id",   # Unique, kebab-case
            priority=50,                   # 0-99, lower runs first
            terminal=False,                # True = blocking, False = advisory
            tags=["project", "workflow"],   # For categorisation
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True if this handler should process the event."""
        ...

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Execute handler logic, return decision + context."""
        ...

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return at least one acceptance test definition."""
        ...
```

## See Also

- [PROJECT_HANDLERS.md](../../CLAUDE/PROJECT_HANDLERS.md) - Full developer guide
- [HANDLER_DEVELOPMENT.md](../../CLAUDE/HANDLER_DEVELOPMENT.md) - Handler development guide
