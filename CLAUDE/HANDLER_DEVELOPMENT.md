# Handler Development Guide

Guide for creating new handlers for claude-code-hooks-daemon.

> **Run every command below from the PROJECT ROOT.** Paths like
> `./bin/hooks-daemon` and `./scripts/qa/...` are relative to it, and resolve to
> nothing from anywhere else (`exit 127`).

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

## ⚠️ When NOT to Write a Handler

**CRITICAL**: Handlers are for **deterministic validation only**. If your logic requires reasoning, context analysis, or multi-turn investigation, **use Claude Code's native agent-based hooks instead**.

### Don't Write a Handler If:

❌ **Requires analyzing session context**

- Reading session transcripts to detect agent type
- Checking if specific workflow steps were followed
- Determining if operations are part of structured process

❌ **Needs multi-turn reasoning**

- "Is this change architecturally sound?"
- "Does this follow our planning workflow?"
- "Is the release process being followed?"

❌ **Requires reading/analyzing files**

- Parsing git history to understand intent
- Reading multiple files to validate patterns
- Complex file content analysis

❌ **Involves judgment calls**

- "Is this a reasonable refactoring?"
- "Does this align with project standards?"
- "Should this be allowed in this context?"

### Use Native Agent Hooks Instead

For complex validation, add an agent-based hook to `.claude/settings.json` —
the same file the daemon's own registrations live in, alongside them rather
than instead of them. (`type: agent` is documented as experimental and may
change; `type: prompt` is the stable single-turn equivalent, with no tool
access and a 30s default timeout against the agent hook's 60s.)

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": {"tool": "Bash", "pattern": "git tag"},
      "hooks": [{
        "type": "agent",
        "prompt": "Analyze session context and validate workflow compliance...",
        "timeout": 60
      }]
    }]
  }
}
```

**See [ARCHITECTURE.md](./ARCHITECTURE.md) for complete guidance on when to use daemon handlers vs native agent hooks.**

### Write a Handler If:

✅ **Simple pattern matching**

- Regex checks: `git reset --hard`, `sed -i`, `rm -rf`
- String contains: `# noqa`, `--force`, `--break-system-packages`

✅ **Deterministic validation**

- File path validation (absolute vs relative)
- File extension checks
- Command flag detection

✅ **Fast, synchronous checks**

- No file reads required (beyond hook_input)
- No external command execution needed
- Known input → known output

✅ **Reusable across projects**

- Same validation logic applies everywhere
- Configurable enable/disable per project

## Quick Start

```python
from claude_code_hooks_daemon.core import GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command

class MyHandler(PreToolUseHandlerBase):
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

    def handle(self, hook_input: dict) -> GatingResult:
        """Execute handler logic, return result."""
        return GatingResult.deny(
            reason="This operation is not allowed because..."
        )
```

## Subclass your event's base, not `Handler`

**Your handler's base class is chosen by the event it answers**, and it decides
which decisions you are allowed to return.

This is not a style preference. `PreToolUse` carries a refusal as
`permissionDecision: deny`; `Stop` carries one as `decision: block`;
`SessionStart` has no way to express a refusal at all. A DENY on an event that
cannot carry one is **silently dropped on the wire** — the handler believes it
blocked and nothing blocked. Subclassing the event's base makes that
unwritable: mypy rejects the decision, and Pydantic rejects it again at runtime.

| Tier         | Decisions it can return           | Events                                                                                                                                                                   | Base class           | Result type      |
| ------------ | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------- | ---------------- |
| **Gating**   | allow, continue, deny, ask, defer | PreToolUse                                                                                                                                                               | `<Event>HandlerBase` | `GatingResult`   |
| **Blocking** | allow, continue, deny             | PostToolUse, Stop, SubagentStop, PermissionRequest, UserPromptSubmit, PreCompact, UserPromptExpansion, PostToolUseFailure, PostToolBatch, TaskCreated, TaskCompleted, TeammateIdle, ConfigChange | `<Event>HandlerBase` | `BlockingResult` |
| **Advisory** | allow, continue                   | every other wired event                                                                                                                                                  | `<Event>HandlerBase` | `AdvisoryResult` |

The tier assignments come from the DOCUMENTED hooks contract, vendored under
`contracts/claude-code-hooks/` and enforced by the `hook_contract` QA check
(Plan 00271). PreToolUse additionally supports `updatedInput` (set
`HookResult.updated_input` to rewrite the tool's entire input object before it
runs) and `GatingResult.defer()` (exit gracefully so the tool resumes later).
A PermissionRequest deny's reason reaches Claude via the documented
`decision.message` field.

**Every wired event has a base named after it** — `SessionStartHandlerBase`,
`PostToolUseHandlerBase`, `StatusLineHandlerBase`, and so on, in
`claude_code_hooks_daemon.core.handler_bases`. Use your event's name and you do
not need to know which tier it is in; that is the whole point. (The names are
aliases of the three tier classes, so `SessionStartHandlerBase is AdvisoryHandler` — which is why an event's base cannot drift from its tier.)

Build results through the result type, not `HookResult`:

```python
return AdvisoryResult.allow(context=["FYI: ..."])   # advisory tier
return BlockingResult.deny(reason="Lint failed")    # blocking tier
return GatingResult.ask(reason="Confirm?")          # gating tier
```

`AdvisoryResult.deny(...)` does not compile — `deny` is inherited from
`HookResult` and returns the wide type, so your declared `-> AdvisoryResult`
rejects it. That is deliberate, and it is the error you want.

**A pseudo-event handler is the one exception.** Its decision is delivered under
whichever REAL event triggered it, and triggers are per-project configuration —
so no fixed tier is correct. Those subclass `Handler` directly and are clamped
at merge time instead.

## Handler Pattern

### 1. Class Definition

Subclass the base named after your event — see
[Subclass your event's base](#subclass-your-events-base-not-handler) above.

```python
class MyHandler(PreToolUseHandlerBase):
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
def handle(self, hook_input: dict) -> GatingResult:
    """Execute the handler logic.

    The return type is your EVENT's result type, not `HookResult` — widening it
    back is rejected by mypy, which is what stops a handler returning a decision
    its event silently drops.

    Args:
        hook_input: Same dict passed to matches()

    Returns:
        A result of this event's tier, with decision and optional reason/context
    """
    command = get_bash_command(hook_input)

    return GatingResult(
        decision=Decision.DENY,  # ALLOW, DENY or ASK — the gating tier carries all three
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
class MyHandler(PreToolUseHandlerBase):
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

#### Behaviour Tags

Describe handler behaviour:

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
4. **What behaviour?** (terminal/non-terminal, blocking)
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

| Priority Range | Type         | Examples                                              |
| -------------- | ------------ | ----------------------------------------------------- |
| 0-9            | Test         | Purpose-built test fixtures (`Priority.TEST_HANDLER`) |
| 10-20          | Safety       | Destructive git, sed blocker, data loss prevention    |
| 25-35          | Code Quality | QA suppression blockers, ESLint disable               |
| 36-55          | Workflow     | TDD enforcement, plan validation, web search          |
| 56-60          | Advisory     | British English warnings, suggestions                 |
| 100+           | Logging      | Notification logger, session cleanup                  |

**Lower priority = runs first**

## Terminal vs Non-Terminal

### Terminal Handlers (default: True)

**Use when**: You need to **block or enforce**

```python
class BlockDangerousBashHandler(PreToolUseHandlerBase):
    def __init__(self):
        super().__init__(name="block-dangerous-bash", priority=10, terminal=True)

    def handle(self, hook_input: dict) -> GatingResult:
        return GatingResult.deny(reason="Blocked!")
```

**Behaviour**:

- Stops dispatch immediately
- Decision becomes final result
- No other handlers run after this

### Non-Terminal Handlers (terminal=False)

**Use when**: You want to **warn or guide** without blocking

```python
class SpellingAdviceHandler(PreToolUseHandlerBase):
    def __init__(self):
        super().__init__(name="spelling-advice", priority=60, terminal=False)

    def handle(self, hook_input: dict) -> GatingResult:
        return GatingResult.allow(
            context=["⚠️  Warning: This might cause issues..."]
        )
```

**Behaviour**:

- Provides context/guidance
- Allows subsequent handlers to run
- Decision is ignored (always treated as allow)
- Context accumulated into final result

## Result Options

The class you construct is your event's tier — `AdvisoryResult`,
`BlockingResult` or `GatingResult`. Options 1-3 work on every tier; option 4
needs blocking or gating; option 5 needs gating. Using one your tier does not
carry is a mypy error, which is the point.

### 1. Allow (silent) — any tier

```python
return AdvisoryResult(decision=Decision.ALLOW)
```

### 2. Allow with context — any tier

```python
return AdvisoryResult(
    decision=Decision.ALLOW,
    context=["📋 Reminder: Don't forget to update documentation"]
)
```

### 3. Allow with guidance — any tier

```python
return AdvisoryResult(
    decision=Decision.ALLOW,
    guidance="Consider using X instead of Y for better performance"
)
```

### 4. Deny (block) — blocking or gating tier only

```python
return GatingResult(
    decision=Decision.DENY,
    reason="Clear explanation of why operation is blocked"
)
```

### 5. Ask (request approval) — gating tier only

```python
return GatingResult(
    decision=Decision.ASK,
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

class RegexHandler(PreToolUseHandlerBase):
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
class FileTypeHandler(PreToolUseHandlerBase):
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
class ContentHandler(PreToolUseHandlerBase):
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
class MultiToolHandler(PreToolUseHandlerBase):
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
return GatingResult(decision=Decision.DENY, reason="Command blocked")
```

✅ Good:

```python
return GatingResult(
    decision=Decision.DENY,
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

````python
class StrictHandler(PreToolUseHandlerBase):
    ESCAPE_HATCH = "I CONFIRM THIS IS NECESSARY"

    def handle(self, hook_input: dict) -> GatingResult:
        command = get_bash_command(hook_input)

        # Check for escape hatch phrase
        if self.ESCAPE_HATCH in command:
            return GatingResult(decision=Decision.ALLOW)

        return GatingResult(
            decision=Decision.DENY,
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
def handle(self, hook_input: dict) -> BlockingResult:
    # ✅ No need to check if tool_response exists - validation guarantees it
    tool_response = hook_input["tool_response"]

    # ✅ No need to handle tool_output typo - validation rejects it
    stderr = tool_response.get("stderr", "")

    # ❌ Still need business logic
    if "error" in stderr.lower():
        return BlockingResult(decision=Decision.DENY, reason="Command failed")

    return BlockingResult(decision=Decision.ALLOW)
````

**When validation is disabled**: Handlers should still defensively check for required fields using `.get()` with defaults

## `get_claude_md()` — does your handler earn resident context?

`get_claude_md()` is abstract, so you MUST implement it. That makes it easy to
write `return None` to satisfy the compiler and move on — which is not a
decision, it is a deferral. Answer the question properly, because whichever
way you answer, someone pays.

**What a section costs.** Everything returned here is inlined into the
project's `CLAUDE.md` and read IN FULL at the start of every session, whether
or not your handler ever fires. Measured on this repository: the injected
block is ~73 KB across 53 sections — **68% of the whole file**, ~18,300 tokens
per session. The mean section costs ~345 tokens *forever*. Returning content
is the expensive answer; returning `None` is not the lazy one.

Apply these four tests in order. First YES earns a section; reaching the end
means `None`.

1. **Can the handler DENY a tool call?** A denial burns a turn, and Claude
   Code cancels every sibling tool call batched with the denied one. Guidance
   that prevents one denial has already paid for itself. → YES earns.

2. **Is the advice too late for the call it fires on?** If the choice being
   advised about is already baked into the allowed call (`agent_isolation_advisor`
   fires as the agent is already spawning), the agent cannot act on it without
   redoing work → earns. If the advice governs what happens NEXT and arrives
   before it (an advisory that fires as a Task starts and describes the cycle
   that Task is about to run) → does not earn.

3. **Is it a standing policy rather than a one-shot correction?** Advice the
   agent must hold across many later decisions decays after one delivery
   (`recovery_cron_advisor`: "never treat the cron as a heartbeat"). Stop-time
   behavioural advisories always qualify — they can only ever fire *after* the
   message that broke the norm, so resident text is the only preventive form.
   → YES earns.

4. **Would a reader who already has the fire-time message, and the rest of the
   block, learn anything?** This one OVERRIDES the others. Restating your own
   fire-time message is duplication; restating another handler's section is
   worse, because the fact is now billed twice per session and the two copies
   drift apart. → NO does not earn.

   **If you claim another section covers you, OPEN THAT SECTION AND CHECK IT** —
   for the same triggers AND the same failure behaviour. Both halves, because
   this is where the criterion was first got wrong: `validate_eslint_on_write`
   was exempted as "the ESLint case of `lint_on_edit`", but that section lists
   nine languages without TypeScript among them, and promises that a missing or
   timed-out linter never blocks — while the ESLint handler denies on both. The
   section claimed to cover it stated a guarantee that was false for the very
   case it was supposed to cover, which is worse than saying nothing. A partial
   overlap is not cover.

Handlers that emit nothing an agent acts on — status-line renderers, loggers,
lifecycle handlers — never reach the tests and are always `None`.

**Whichever you decide, record it.** Add your handler to the classification
table in `tests/integration/test_claude_md_guidance_coverage.py`. An exemption
carries a reason string, so the next person auditing coverage reads your
reasoning instead of re-deriving it. The test fails if a handler appears in
neither list.

## Checklist

Before submitting handler:

- [ ] Clear, descriptive name (kebab-case)
- [ ] Appropriate priority (see guide)
- [ ] Terminal flag set correctly
- [ ] Comprehensive docstring
- [ ] Efficient pattern matching (regex compiled in __init__)
- [ ] Clear error messages with alternatives
- [ ] `get_claude_md()` answered against the four tests above, and the verdict
  recorded in the guidance-coverage classification table
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
- **Environment detection**: `status_line/environment_indicator.py` — renders 💻 or a
  container icon from the runtime `ProjectContext` detected, so the detection itself
  lives in `ProjectContext` and the handler stays a thin reader of it

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
from claude_code_hooks_daemon.core import GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase

class ProjectRulesHandler(PreToolUseHandlerBase):
    def __init__(self) -> None:
        super().__init__(name="project-rules", priority=40, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        # Your project-specific logic
        return True

    def handle(self, hook_input: dict) -> GatingResult:
        return GatingResult.allow(context=["✅ Project rules OK"])
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
class Handler1(PreToolUseHandlerBase):
    def __init__(self) -> None:
        super().__init__(name="handler-1", priority=30)
    # ... implementation

class Handler2(PreToolUseHandlerBase):
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

## Project-Level Handlers

Project-level handlers are the recommended approach for project-specific handler logic. They use the same `Handler` ABC but live in the project repository and are auto-discovered by convention.

### Key Differences from Built-in Handlers

| Aspect      | Built-in                                 | Project-Level                            |
| ----------- | ---------------------------------------- | ---------------------------------------- |
| Location    | `src/claude_code_hooks_daemon/handlers/` | `.claude/project-handlers/`              |
| Discovery   | `pkgutil.walk_packages`                  | `importlib.util.spec_from_file_location` |
| Handler IDs | `HandlerID` enum constants               | Plain string `handler_id`                |
| Config      | Per-handler enable/disable/priority      | Master switch only                       |
| Tests       | Separate `tests/` tree                   | Co-located `test_` files                 |
| Scope       | Reusable across projects                 | Project-specific                         |

### When to Use Project Handlers

- **Project-specific workflow reminders** (vendor commit workflow, asset rebuilds, migration reminders)
- **Project-specific convention enforcement** (branch naming, file structure)
- **Tool-specific reminders** scoped to one project's toolchain

### When to Use Built-in Handlers

- **Cross-project safety** (destructive git, sed blocking, absolute path enforcement)
- **Language-level quality enforcement** (QA suppression blocking)
- **Reusable patterns** that apply to many projects

### Quick Example

```python
# .claude/project-handlers/post_tool_use/build_asset_watcher.py
from typing import Any
from claude_code_hooks_daemon.core import AcceptanceTest, BlockingResult, TestType
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.utils import get_file_path

class BuildAssetWatcherHandler(PostToolUseHandlerBase):
    """Remind to rebuild assets after editing TS/SCSS sources."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="build-asset-watcher",
            priority=50,
            terminal=False,
            tags=["project", "build", "frontend"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        file_path = get_file_path(hook_input)
        if not file_path:
            return False
        return "assets/ts/" in file_path or "assets/scss/" in file_path

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        return BlockingResult(
            decision=Decision.ALLOW,
            context=["ASSET BUILD REMINDER: Run 'yarn build' to rebuild compiled assets."],
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="TS edit triggers build reminder",
                command='echo "Edit TS file"',
                description="Advisory reminder when editing TypeScript source",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"ASSET BUILD REMINDER"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.ADVISORY,
            ),
        ]
```

### CLI Commands

```bash
# Scaffold directory structure
./bin/hooks-daemon init-project-handlers

# Validate all handlers load correctly
./bin/hooks-daemon validate-project-handlers

# Run project handler tests
./bin/hooks-daemon test-project-handlers --verbose
```

### Testing with Daemon Infrastructure

Project handler tests use the daemon's pytest and venv. Co-located `conftest.py` provides standard fixtures (`bash_hook_input`, `write_hook_input`, `edit_hook_input`).

Tests run via:

```bash
./bin/hooks-daemon test-project-handlers
```

Acceptance tests defined in `get_acceptance_tests()` are automatically included in the playbook generated by `generate-playbook`.

**Full documentation**: See [PROJECT_HANDLERS.md](PROJECT_HANDLERS.md) for the complete developer guide.

## Questions?

- See `ARCHITECTURE.md` for system design
- See `PROJECT_HANDLERS.md` for project-level handler guide
- See existing handlers for examples
- Check GitHub Issues for discussions
