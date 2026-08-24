# Example Project Handlers

These examples demonstrate common project handler patterns. Copy and adapt them for your own project.

## Examples

### 1. Vendor Changes Reminder (PreToolUse, Advisory)

**File**: `pre_tool_use/vendor_changes_reminder.py`

Detects `git add`/`git commit` commands that include vendor paths and provides an advisory reminder about the first-party vendor commit workflow. Non-terminal (advisory only).

**Pattern**: Bash command matching with regex, advisory context injection.

### 2. Branch Naming Enforcer (SessionStart, Advisory)

**File**: `session_start/branch_naming_enforcer.py`

Checks the current git branch name against allowed patterns at session start and reports a non-conforming branch as context. Non-terminal (advisory only).

**Pattern**: SessionStart check with subprocess, advisory context injection — and a worked example of matching the decision to what the EVENT can deliver. `SessionStart` cannot carry a refusal, so this handler subclasses `SessionStartHandlerBase`, which narrows `handle()` to `AdvisoryResult` and makes a dropped refusal a compile error rather than a silent no-op. To BLOCK work on a badly-named branch, put the check on `PreToolUse` instead.

### 3. Build Asset Watcher (PostToolUse, Advisory)

**File**: `post_tool_use/build_asset_watcher.py`

Detects writes to TypeScript/SCSS source files and reminds to rebuild compiled assets. Non-terminal (advisory only).

**Pattern**: File path matching on PostToolUse events, advisory context injection.

## How to Use

1. Copy the example handler and test file to your `.claude/project-handlers/` directory
2. Adapt the matching logic, handler ID, and context messages to your project
3. Run tests: `.claude/hooks-daemon/bin/hooks-daemon test-project-handlers --verbose`
4. Validate: `.claude/hooks-daemon/bin/hooks-daemon validate-project-handlers`
5. Restart daemon: `.claude/hooks-daemon/bin/hooks-daemon restart`

## Handler Anatomy

Every project handler follows this structure. The base class you subclass
depends on the EVENT, not on whether your handler happens to block: each
wired event has a matching base in `core.handler_bases` (`PreToolUseHandlerBase`
below is one of them) that narrows `handle()` to the result type that event
can actually deliver — plain `Handler`/`HookResult` still works, but it
cannot catch a decision the event will silently drop on the wire.

```python
from typing import Any
from claude_code_hooks_daemon.core import AcceptanceTest, GatingResult, TestType
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision

class MyHandler(PreToolUseHandlerBase):
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

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Execute handler logic, return decision + context."""
        ...

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return at least one acceptance test definition."""
        ...
```

## See Also

- [PROJECT_HANDLERS.md](../../CLAUDE/PROJECT_HANDLERS.md) - Full developer guide
- [HANDLER_DEVELOPMENT.md](../../CLAUDE/HANDLER_DEVELOPMENT.md) - Handler development guide
