# Handler Development Guide

Guide for creating new handlers for claude-code-hooks-daemon.

## 🔍 CRITICAL: Debug First, Develop Second

**Before writing any handler**, use the debugging tool to capture exact event flows:

```bash
./scripts/debug_hooks.sh start "Testing scenario X"
# Perform your test scenario in Claude Code
./scripts/debug_hooks.sh stop
```

This shows you:
- Which events fire (PreToolUse, PostToolUse, SubagentStart, etc.)
- What data is in `hook_input`
- What order events fire in
- Which existing handlers run

**See [DEBUGGING_HOOKS.md](./DEBUGGING_HOOKS.md) for complete introspection guide.**

Without debugging first, you're guessing which events to hook and what data is available. With debugging, you're surgically precise.

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

## Handler Tagging System

### Overview

Handlers can be tagged with metadata that enables categorization and filtering. Tags allow users to enable/disable handler groups based on language, functionality, or project specificity.

### Adding Tags to Handlers

Tags are specified in the handler's `__init__` method:

```python
class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            name="my-handler",
            priority=50,
            terminal=True,
            tags=["python", "qa-enforcement", "blocking"]
        )
```

### Tag Taxonomy

#### Language Tags
Use language tags to identify handlers specific to programming languages:
- `python`, `php`, `typescript`, `javascript`, `go`, `rust`, `java`, `ruby`

#### Function Tags
Describe what the handler does:
- `safety` - Prevents destructive operations
- `tdd` - Test-driven development enforcement
- `qa-enforcement` - Enforces code quality standards
- `qa-suppression-prevention` - Blocks lazy QA tool suppressions
- `workflow` - Workflow automation/guidance
- `advisory` - Non-blocking suggestions
- `validation` - Validates code/files/state
- `logging` - Logs events/actions
- `cleanup` - Cleanup operations

#### Tool Tags
Identify which Claude Code tools the handler works with:
- `git`, `npm`, `bash`, `write`, `edit`

#### Behavior Tags
Describe handler behavior:
- `terminal` - Stops dispatch chain
- `non-terminal` - Allows fall-through
- `blocking` - Can deny operations

#### Project Specificity Tags
Indicate project-specific functionality:
- `ec-specific` - Edmonds Commerce-specific
- `project-specific` - Tied to specific project structures
- `generic` - Universally applicable

### Choosing Tags

When creating a handler, add tags that answer:
1. **What language?** (if applicable)
2. **What function?** (safety, qa-enforcement, workflow, etc.)
3. **What tool?** (if specific to git, npm, bash, etc.)
4. **What behavior?** (terminal/non-terminal, blocking)
5. **How specific?** (generic, project-specific, ec-specific)

### Examples

**Safety Handler (Git):**
```python
tags=["safety", "git", "blocking", "terminal"]
```

**QA Suppression Blocker (Python):**
```python
tags=["python", "qa-suppression-prevention", "blocking", "terminal"]
```

**Workflow Advisory (Non-blocking):**
```python
tags=["workflow", "planning", "advisory", "non-terminal"]
```

**Project-Specific Validator:**
```python
tags=["validation", "ec-specific", "project-specific", "advisory", "non-terminal"]
```

### Tag-Based Filtering

Users can filter handlers using tags in configuration:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python, typescript, safety]  # Only these tags
    disable_tags: [ec-specific]                 # Exclude these tags
```

**Filtering Logic:**
- `enable_tags`: Handler must have **at least one** tag from the list
- `disable_tags`: Handler must have **no tags** from the list
- Per-handler `enabled: false` overrides tag filtering

### Best Practices

1. **Be specific**: Use multiple tags to accurately describe functionality
2. **Language first**: Always include language tags for language-specific handlers
3. **Function over tool**: Prioritize function tags (what it does) over tool tags (how it does it)
4. **Document project-specific**: Always tag project-specific handlers with `project-specific` or `ec-specific`
5. **Test filtering**: Test that your handler respects tag-based filtering

### Testing Tagged Handlers

Test that tags work correctly:

```python
def test_handler_tags():
    """Verify handler has correct tags."""
    handler = MyHandler()
    assert "python" in handler.tags
    assert "qa-enforcement" in handler.tags

def test_tag_filtering():
    """Verify handler respects tag filtering."""
    handler = MyHandler()

    # Should match enable_tags
    enable_tags = ["python"]
    assert any(tag in handler.tags for tag in enable_tags)

    # Should not match disable_tags
    disable_tags = ["ec-specific"]
    assert not any(tag in handler.tags for tag in disable_tags)
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

### 5. Trust Input Validation (v2.2.0+)

**Input validation is enabled by default** since v2.2.0. The front controller validates all events before dispatching to handlers.

✅ What handlers can trust:
- Field names are correct (`tool_response` not `tool_output`)
- Required fields are present
- Event structure matches documented schema
- Type safety for core fields

❌ What handlers still need to check:
- Business logic (e.g., "is this git command destructive?")
- Content validation (e.g., "does this contain banned words?")
- Resource limits (e.g., "is this file too large?")

**Example**: PostToolUse handler
```python
def handle(self, hook_input: dict) -> HookResult:
    # ✅ No need to check if tool_response exists - validation guarantees it
    tool_response = hook_input["tool_response"]

    # ✅ No need to handle tool_output typo - validation rejects it
    stderr = tool_response.get("stderr", "")

    # ❌ Still need business logic
    if "error" in stderr.lower():
        return HookResult(decision="deny", reason="Command failed")

    return HookResult(decision="allow")
```

**When validation is disabled**: Handlers should still defensively check for required fields using `.get()` with defaults

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
- **Environment detection**: `yolo_container_detection.py`

### Example: Environment Detection Handler (YoloContainerDetection)

**Use Case**: Detect YOLO container environments and provide informational context to Claude during SessionStart.

**Handler Type**: Non-terminal, advisory (informational only)

**Key Patterns**:
- Multi-tier confidence scoring system
- Environment variable checking
- Filesystem checking with error handling
- Fail-open error handling (never blocks)
- Configurable thresholds and output

**Implementation**:

```python
from claude_code_hooks_daemon.core import Handler, HookResult
import os
from pathlib import Path

class YoloContainerDetectionHandler(Handler):
    """Detects YOLO container environments using confidence scoring."""

    def __init__(self) -> None:
        super().__init__(
            name="yolo-container-detection",
            priority=40,  # Workflow range
            terminal=False  # Allow other handlers to run
        )
        self.config = {
            "min_confidence_score": 3,
            "show_detailed_indicators": True,
            "show_workflow_tips": True,
        }

    def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration overrides."""
        self.config.update(config)

    def _calculate_confidence_score(self) -> int:
        """
        Calculate confidence score based on detected indicators.

        Primary indicators (3 points each):
          - CLAUDECODE=1 environment variable
          - CLAUDE_CODE_ENTRYPOINT=cli environment variable
          - Working directory is /workspace with .claude/ present

        Secondary indicators (2 points each):
          - DEVCONTAINER=true environment variable
          - IS_SANDBOX=1 environment variable
          - container=podman/docker environment variable

        Tertiary indicators (1 point each):
          - Unix socket at .claude/hooks-daemon/untracked/venv/socket
          - Running as root user (UID 0)

        Returns:
            Confidence score (0-12 range)
        """
        score = 0

        try:
            # Primary indicators (3 points each)
            if os.environ.get("CLAUDECODE") == "1":
                score += 3
            if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "cli":
                score += 3

            # Filesystem check with error handling
            try:
                if Path.cwd() == Path("/workspace"):
                    if Path(".claude").exists():
                        score += 3
            except (OSError, RuntimeError):
                pass  # Skip on filesystem errors

            # Secondary indicators (2 points each)
            if os.environ.get("DEVCONTAINER") == "true":
                score += 2
            if os.environ.get("IS_SANDBOX") == "1":
                score += 2
            if os.environ.get("container", "") in ["podman", "docker"]:
                score += 2

            # Tertiary indicators (1 point each)
            try:
                socket_path = Path(".claude/hooks-daemon/untracked/venv/socket")
                if socket_path.exists():
                    score += 1
            except (OSError, RuntimeError):
                pass

            try:
                if os.getuid() == 0:  # Root user
                    score += 1
            except AttributeError:
                pass  # Not available on Windows

        except Exception:
            # Fail open - return 0 score on unexpected errors
            return 0

        return score

    def matches(self, hook_input: dict[str, Any] | None) -> bool:
        """Check if handler should run."""
        if hook_input is None or not isinstance(hook_input, dict):
            return False

        # Only match SessionStart events
        if hook_input.get("hook_event_name") != "SessionStart":
            return False

        # Check confidence score against threshold
        try:
            score = self._calculate_confidence_score()
            threshold = self.config.get("min_confidence_score", 3)
            return score >= threshold
        except Exception:
            return False  # Fail open

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Provide YOLO container detection context."""
        try:
            context = [
                "🐳 Running in YOLO container environment (Claude Code CLI in sandbox)"
            ]

            # Add detailed indicators if enabled
            if self.config.get("show_detailed_indicators", True):
                indicators = self._get_detected_indicators()
                if indicators:
                    context.append("Detected indicators:")
                    for indicator in indicators:
                        context.append(f"  • {indicator}")

            # Add workflow tips if enabled
            if self.config.get("show_workflow_tips", True):
                context.append("")
                context.append("Container workflow implications:")
                context.append("  • Full development environment available")
                context.append("  • Storage is ephemeral - commit and push to persist")
                context.append("  • Running as root - install packages freely")
                context.append("  • Fast iteration enabled (YOLO mode)")

            return HookResult(decision="allow", reason=None, context=context)

        except Exception:
            # Fail open - return ALLOW with no context on errors
            return HookResult(decision="allow", reason=None, context=[])
```

**Key Takeaways**:

1. **Confidence Scoring**: Use multi-tier scoring to avoid false positives
   - Primary indicators (strong signals): 3 points
   - Secondary indicators (moderate signals): 2 points
   - Tertiary indicators (weak signals): 1 point
   - Threshold prevents single weak signal from triggering

2. **Error Handling**: Fail open at every level
   - Try/except around each indicator check
   - Return safe defaults on errors
   - Never crash or block on exceptions

3. **Filesystem Safety**:
   ```python
   try:
       if Path.cwd() == Path("/workspace"):
           if Path(".claude").exists():
               score += 3
   except (OSError, RuntimeError):
       pass  # Skip on filesystem errors
   ```

4. **Platform Compatibility**:
   ```python
   try:
       if os.getuid() == 0:  # Root user check
           score += 1
   except AttributeError:
       pass  # os.getuid() not available on Windows
   ```

5. **Non-Terminal Pattern**: `terminal=False` allows other handlers to run
   - Provides context without stopping dispatch
   - Accumulates informational messages
   - Good for advisory/informational handlers

6. **Configurable Behavior**:
   ```yaml
   session_start:
     yolo_container_detection:
       enabled: true
       priority: 40
       min_confidence_score: 3      # Adjust threshold
       show_detailed_indicators: true   # Toggle detail level
       show_workflow_tips: true     # Toggle tips
   ```

7. **Testing Pattern**: Mock environment in tests
   ```python
   def test_detection(self, monkeypatch):
       # Clear all YOLO indicators first
       for key in ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", ...]:
           monkeypatch.delenv(key, raising=False)

       # Set exactly what you want to test
       monkeypatch.setenv("CLAUDECODE", "1")

       # Mock filesystem
       with patch("pathlib.Path.cwd", return_value=Path("/home/user")):
           with patch("pathlib.Path.exists", return_value=False):
               handler = YoloContainerDetectionHandler()
               score = handler._calculate_confidence_score()
               assert score == 3  # Exactly one primary indicator
   ```

**When to Use This Pattern**:
- Detecting runtime environments
- Providing contextual information
- Advisory messages without blocking
- Multi-signal confidence-based decisions
- Platform-specific feature detection

## Plugin Configuration

### Registering Project-Level Handlers

After creating a handler in `.claude/hooks/handlers/`, register it in `.claude/hooks-daemon.yaml`:

```yaml
# .claude/hooks-daemon.yaml
version: "1.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
      priority: 10

# Project-specific handlers
plugins:
  paths: []  # Optional: additional Python paths to search
  plugins:   # List of plugin configurations
    # File-based plugin (single handler)
    - path: ".claude/hooks/handlers/pre_tool_use/my_handler.py"
      event_type: pre_tool_use  # REQUIRED: which hook event to register for
      handlers: ["MyHandler"]  # Optional: specific classes to load
      enabled: true

    # Module-based plugin (multiple handlers)
    - path: ".claude/hooks/handlers/post_tool_use/"
      event_type: post_tool_use  # REQUIRED
      handlers: null  # null = load all Handler classes
      enabled: true

    # External plugin (from separate package)
    - path: "my_plugin_package.handlers"
      event_type: session_start  # REQUIRED
      handlers: ["CustomHandler"]
      enabled: true
```

### PluginsConfig Structure

**Fields**:
- `paths`: List of additional directories to search for plugins (optional)
- `plugins`: List of plugin configurations

**Each plugin configuration**:
- `path`: Path to Python file or module (required)
  - File: `.claude/hooks/handlers/pre_tool_use/my_handler.py`
  - Module: `.claude/hooks/handlers/pre_tool_use` or `package.module`
  - Relative paths resolve from project root
- `event_type`: Hook event to register handler for (required)
  - Valid values: `pre_tool_use`, `post_tool_use`, `session_start`, `session_end`, `stop`, `subagent_stop`, `pre_compact`, `status_line`, `permission_request`, `notification`, `user_prompt_submit`
  - Handlers are registered only for the specified event type
- `handlers`: List of handler class names to load (optional)
  - `null` or omitted: Load all Handler subclasses found
  - `["ClassName"]`: Load only specified classes
- `enabled`: Whether to load this plugin (default: true)

**Important Requirements**:
- All plugin handlers MUST implement `get_acceptance_tests()` returning a non-empty list
- Handlers without acceptance tests will log a warning but still load (fail-open)

### Example: Project-Level Handler Registration

1. **Create handler** in `.claude/hooks/handlers/pre_tool_use/project_rules.py`:

```python
from claude_code_hooks_daemon.core import Handler, HookResult

class ProjectRulesHandler(Handler):
    def __init__(self) -> None:
        super().__init__(name="project-rules", priority=40, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        # Your project-specific logic
        return True

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="allow", context="✅ Project rules OK")
```

2. **Register in config** (`.claude/hooks-daemon.yaml`):

```yaml
plugins:
  paths: []
  plugins:
    - path: ".claude/hooks/handlers/pre_tool_use/project_rules.py"
      event_type: pre_tool_use  # REQUIRED: specifies which hook event
      handlers: ["ProjectRulesHandler"]
      enabled: true
```

3. **Test handler**:
```bash
# Handler will now run on all PreToolUse events
# Verify with: .claude/hooks/pre-tool-use < test-input.json
```

### Multiple Handlers in One File

```python
# .claude/hooks/handlers/pre_tool_use/my_handlers.py
class Handler1(Handler):
    def __init__(self) -> None:
        super().__init__(name="handler-1", priority=30)
    # ... implementation

class Handler2(Handler):
    def __init__(self) -> None:
        super().__init__(name="handler-2", priority=40)
    # ... implementation
```

```yaml
# Load both handlers
plugins:
  paths: []
  plugins:
    - path: ".claude/hooks/handlers/pre_tool_use/my_handlers.py"
      event_type: pre_tool_use  # REQUIRED
      handlers: null  # Load all Handler subclasses
      enabled: true

# Or load selectively
plugins:
  paths: []
  plugins:
    - path: ".claude/hooks/handlers/pre_tool_use/my_handlers.py"
      event_type: pre_tool_use  # REQUIRED
      handlers: ["Handler1"]  # Only load Handler1
      enabled: true
```

## Questions?

- See `ARCHITECTURE.md` for system design
- See existing handlers for examples
- Check GitHub Issues for discussions
