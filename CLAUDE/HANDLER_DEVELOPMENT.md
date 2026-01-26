# Handler Development Guide

Guide for creating new handlers for claude-code-hooks-daemon.

## Quick Start

```python
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command

class MyHandler(Handler):
    """One-line description of what this handler does."""

    def __init__(self):
        super().__init__(
            name="my-handler",      # Unique identifier
            priority=50,            # 5-60 range (lower runs first)
            terminal=True           # Stop dispatch after execution?
        )

    def matches(self, hook_input: dict) -> bool:
        """Return True if this handler should execute."""
        command = get_bash_command(hook_input)
        return command and "dangerous-pattern" in command

    def handle(self, hook_input: dict) -> HookResult:
        """Execute handler logic, return result."""
        return HookResult(
            decision="deny",
            reason="This operation is not allowed because..."
        )
```

## Handler Pattern

### 1. Class Definition

```python
class MyHandler(Handler):
    """Docstring explaining what this handler does and why."""
```

### 2. Initialization

```python
def __init__(self):
    super().__init__(
        name="my-handler",  # Unique, descriptive, kebab-case
        priority=50,        # See priority guide below
        terminal=True       # See terminal vs non-terminal below
    )

    # Initialize any patterns, state, or cached data
    self.forbidden_patterns = [
        r'\bgit\s+reset\s+--hard',
        r'\brm\s+-rf\s+/',
    ]
```

### 3. Match Logic

```python
def matches(self, hook_input: dict) -> bool:
    """Check if this handler applies to the given input.

    Args:
        hook_input: Dict with keys:
            - tool_name: Name of tool being used
            - tool_input: Tool-specific parameters
            - description: Optional tool description

    Returns:
        True if handler should execute, False otherwise
    """
    # Example: Only match Bash tool
    if hook_input.get("tool_name") != "Bash":
        return False

    command = get_bash_command(hook_input)
    if not command:
        return False

    # Check for dangerous patterns
    for pattern in self.forbidden_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return True

    return False
```

### 4. Handle Logic

```python
def handle(self, hook_input: dict) -> HookResult:
    """Execute the handler logic.

    Args:
        hook_input: Same dict passed to matches()

    Returns:
        HookResult with decision and optional reason/context
    """
    command = get_bash_command(hook_input)

    return HookResult(
        decision="deny",  # "allow", "deny", or "ask"
        reason=(
            "🚫 BLOCKED: Dangerous command detected\n\n"
            f"Command: {command}\n\n"
            "WHY: This command is blocked because...\n\n"
            "✅ SAFE ALTERNATIVES:\n"
            "  1. Use this instead\n"
            "  2. Or do this\n"
        )
    )
```

## Utility Functions

### Extracting Information from hook_input

```python
from claude_code_hooks_daemon.core.utils import (
    get_bash_command,     # Extract bash command
    get_file_path,        # Extract file path (Write/Edit)
    get_file_content,     # Extract file content (Write)
)

# Get bash command (returns None if not Bash tool)
command = get_bash_command(hook_input)

# Get file path (Write/Edit tools)
file_path = get_file_path(hook_input)

# Get file content (Write tool)
content = get_file_content(hook_input)

# Get tool name
tool_name = hook_input.get("tool_name")

# Get tool input params
tool_input = hook_input.get("tool_input", {})

# For Edit tool
old_string = tool_input.get("old_string")
new_string = tool_input.get("new_string")
```

## Priority Guide

Choose priority based on handler type:

| Priority Range | Type | Examples |
|----------------|------|----------|
| 5-9 | Architecture | Controller pattern enforcement |
| 10-20 | Safety | Destructive git, sed blocker, data loss prevention |
| 21-30 | Code Quality | ESLint disable, TypeScript errors |
| 31-45 | Workflow | TDD enforcement, plan validation |
| 46-60 | Advisory | British English warnings, suggestions |

**Lower priority = runs first**

## Terminal vs Non-Terminal

### Terminal Handlers (default: True)

**Use when**: You need to **block or enforce**

```python
class BlockingHandler(Handler):
    def __init__(self):
        super().__init__(name="blocking", priority=10, terminal=True)

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="deny", reason="Blocked!")
```

**Behavior**:
- Stops dispatch immediately
- Decision becomes final result
- No other handlers run after this

### Non-Terminal Handlers (terminal=False)

**Use when**: You want to **warn or guide** without blocking

```python
class AdvisoryHandler(Handler):
    def __init__(self):
        super().__init__(name="advisory", priority=60, terminal=False)

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(
            decision="allow",  # Ignored for non-terminal
            context="⚠️  Warning: This might cause issues..."
        )
```

**Behavior**:
- Provides context/guidance
- Allows subsequent handlers to run
- Decision is ignored (always treated as allow)
- Context accumulated into final result

## HookResult Options

### 1. Allow (silent)

```python
return HookResult(decision="allow")
```

### 2. Allow with context

```python
return HookResult(
    decision="allow",
    context="📋 Reminder: Don't forget to update documentation"
)
```

### 3. Allow with guidance

```python
return HookResult(
    decision="allow",
    guidance="Consider using X instead of Y for better performance"
)
```

### 4. Deny (block)

```python
return HookResult(
    decision="deny",
    reason="Clear explanation of why operation is blocked"
)
```

### 5. Ask (request approval)

```python
return HookResult(
    decision="ask",
    reason="This operation requires user approval because..."
)
```

## Testing Handlers

### Test Structure

```python
import pytest
from my_handler import MyHandler

class TestMyHandler:
    @pytest.fixture
    def handler(self):
        return MyHandler()

    def test_matches_dangerous_command(self, handler):
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"}
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_safe_command(self, handler):
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"}
        }
        assert handler.matches(hook_input) is False

    def test_blocks_dangerous_command(self, handler):
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"}
        }
        result = handler.handle(hook_input)

        assert result.decision == "deny"
        assert "BLOCKED" in result.reason
        assert "rm -rf" in result.reason
```

### Test Fixtures

Create reusable fixtures in `tests/fixtures/`:

```python
# tests/fixtures/hook_inputs.py
def bash_input(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command}
    }

def write_input(file_path: str, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": content
        }
    }
```

## Common Patterns

### Pattern 1: Regex Matching

```python
import re

class RegexHandler(Handler):
    def __init__(self):
        super().__init__(name="regex", priority=20)
        # Compile patterns once in __init__
        self.patterns = [
            re.compile(r'\bgit\s+reset\s+--hard', re.IGNORECASE),
            re.compile(r'\brm\s+-rf\s+/', re.IGNORECASE),
        ]

    def matches(self, hook_input: dict) -> bool:
        command = get_bash_command(hook_input)
        if not command:
            return False

        return any(pattern.search(command) for pattern in self.patterns)
```

### Pattern 2: File Extension Checking

```python
class FileTypeHandler(Handler):
    EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx']

    def matches(self, hook_input: dict) -> bool:
        if hook_input.get("tool_name") not in ["Write", "Edit"]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        return any(file_path.endswith(ext) for ext in self.EXTENSIONS)
```

### Pattern 3: Content Scanning

```python
class ContentHandler(Handler):
    FORBIDDEN = ["password", "secret", "api_key"]

    def matches(self, hook_input: dict) -> bool:
        if hook_input.get("tool_name") != "Write":
            return False

        content = get_file_content(hook_input)
        if not content:
            return False

        content_lower = content.lower()
        return any(word in content_lower for word in self.FORBIDDEN)
```

### Pattern 4: Multi-Tool Matching

```python
class MultiToolHandler(Handler):
    def matches(self, hook_input: dict) -> bool:
        tool_name = hook_input.get("tool_name")

        if tool_name == "Bash":
            return "dangerous" in get_bash_command(hook_input)
        elif tool_name == "Write":
            return "dangerous" in get_file_content(hook_input)
        elif tool_name == "Edit":
            tool_input = hook_input.get("tool_input", {})
            return "dangerous" in tool_input.get("new_string", "")

        return False
```

## Best Practices

### 1. Clear Error Messages

❌ Bad:
```python
return HookResult(decision="deny", reason="Command blocked")
```

✅ Good:
```python
return HookResult(
    decision="deny",
    reason=(
        "🚫 BLOCKED: Destructive git command\n\n"
        f"Command: {command}\n\n"
        "WHY: This command permanently destroys uncommitted changes.\n\n"
        "✅ SAFE ALTERNATIVES:\n"
        "  1. git commit -m 'WIP' (save changes first)\n"
        "  2. git diff (review changes)\n"
        "  3. git status (see what will be affected)\n"
    )
)
```

### 2. Specific Matching

❌ Bad (too broad):
```python
def matches(self, hook_input: dict) -> bool:
    return "git" in str(hook_input)
```

✅ Good (specific):
```python
def matches(self, hook_input: dict) -> bool:
    command = get_bash_command(hook_input)
    return command and re.search(r'\bgit\s+reset\s+--hard\b', command)
```

### 3. Performance

❌ Bad (slow):
```python
def matches(self, hook_input: dict) -> bool:
    # Compiling regex on every call
    return re.search(r'pattern', get_bash_command(hook_input))
```

✅ Good (fast):
```python
def __init__(self):
    super().__init__(name="handler", priority=10)
    self.pattern = re.compile(r'pattern')  # Compile once

def matches(self, hook_input: dict) -> bool:
    return self.pattern.search(get_bash_command(hook_input))
```

### 4. Escape Hatches

For strict handlers, provide escape hatch:

```python
class StrictHandler(Handler):
    ESCAPE_HATCH = "I CONFIRM THIS IS NECESSARY"

    def handle(self, hook_input: dict) -> HookResult:
        command = get_bash_command(hook_input)

        # Check for escape hatch phrase
        if self.ESCAPE_HATCH in command:
            return HookResult(decision="allow")

        return HookResult(
            decision="deny",
            reason=(
                "Command blocked. If absolutely necessary, include:\n"
                f'"{self.ESCAPE_HATCH}"'
            )
        )
```

## Checklist

Before submitting handler:

- [ ] Clear, descriptive name (kebab-case)
- [ ] Appropriate priority (see guide)
- [ ] Terminal flag set correctly
- [ ] Comprehensive docstring
- [ ] Efficient pattern matching (regex compiled in __init__)
- [ ] Clear error messages with alternatives
- [ ] Unit tests (95%+ coverage)
- [ ] Integration test (full dispatch cycle)
- [ ] Documentation in handler file
- [ ] Example in handler docstring

## Examples

See existing handlers for reference:

- **Simple blocking**: `destructive_git.py`
- **Complex matching**: `sed_blocker.py`
- **Advisory/warning**: `british_english.py`
- **TDD enforcement**: `tdd_enforcement.py`
- **Multi-tool**: `absolute_path.py`

## Questions?

- See `ARCHITECTURE.md` for system design
- See existing handlers for examples
- Check GitHub Issues for discussions
