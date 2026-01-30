# Claude Code Hooks System - Comprehensive Reference

**Version**: January 2026
**Source of Truth**: [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks.md)

This document provides a complete reference for the Claude Code hooks system, covering event types, input/output formats, handler development, and critical guidelines for this project's hooks daemon.

---

## 1. What Are Claude Code Hooks?

Hooks are user-defined shell commands (or LLM prompts) that execute at specific points in Claude Code's lifecycle. They provide **deterministic control** over Claude Code's behavior -- unlike prompt instructions that the LLM may or may not follow, hooks execute as application-level code every time their trigger conditions are met.

### How They Work

1. Claude Code reaches a lifecycle point (e.g., about to execute a tool)
2. It checks settings files for hook configurations matching that event
3. All matching hooks run **in parallel**
4. Hook scripts receive JSON data via **stdin**
5. Hooks communicate back via **exit codes**, **stdout**, and **stderr**
6. Claude Code acts on the hook output (block, allow, inject context, etc.)

### When They Fire

Hooks fire at these points in the session lifecycle:

```
SessionStart
    |
    v
UserPromptSubmit --> Claude thinks --> PreToolUse --> [tool executes] --> PostToolUse
    ^                                      |                                |
    |                                 PermissionRequest                     |
    |                                      |                                |
    +---------- Stop / SubagentStop <------+--------------------------------+
    |
    v
PreCompact (if context full)
    |
    v
SessionEnd
```

### What They Enable

- **Notifications**: Custom alerts when Claude needs input
- **Automatic formatting**: Run formatters after file edits
- **Logging and compliance**: Track all executed commands
- **Feedback**: Provide automated feedback on code that violates conventions
- **Custom permissions**: Block modifications to sensitive files
- **Context injection**: Add dynamic information to Claude's context
- **Workflow enforcement**: Enforce TDD, planning, code review patterns

---

## 2. Available Hook Events

### Event Summary Table

| Hook Event          | When It Fires                          | Can Block? | Has Matcher? |
|---------------------|----------------------------------------|------------|--------------|
| `SessionStart`      | Session begins or resumes              | No         | Yes*         |
| `Setup`             | `--init`, `--init-only`, `--maintenance` | No       | Yes*         |
| `UserPromptSubmit`  | User submits a prompt                  | Yes        | No           |
| `PreToolUse`        | Before tool execution                  | Yes        | Yes          |
| `PermissionRequest` | Permission dialog shown                | Yes        | Yes          |
| `PostToolUse`       | After tool succeeds                    | Feedback   | Yes          |
| `PostToolUseFailure`| After tool fails                       | Feedback   | Yes          |
| `SubagentStart`     | Subagent spawned                       | No         | No           |
| `SubagentStop`      | Subagent finishes                      | Yes        | No           |
| `Stop`              | Claude finishes responding             | Yes        | No           |
| `PreCompact`        | Before context compaction              | No         | Yes*         |
| `Notification`      | Claude sends notification              | No         | Yes*         |
| `SessionEnd`        | Session terminates                     | No         | No           |

*These matchers filter on event subtypes rather than tool names.

### Detailed Event Descriptions

#### SessionStart

**When**: Session begins (new or resumed), after `/clear`, or after compaction.

**Matchers**: `startup`, `resume`, `clear`, `compact`

**Special**: Has access to `CLAUDE_ENV_FILE` for persisting environment variables across the session.

**Use cases**: Loading development context, setting environment variables, detecting runtime environment.

#### Setup

**When**: Claude Code invoked with `--init`, `--init-only`, or `--maintenance` flags.

**Matchers**: `init`, `maintenance`

**Special**: Has access to `CLAUDE_ENV_FILE`. Use this for one-time or occasional operations (dependency installation, migrations) that would slow down every session if run in SessionStart.

#### UserPromptSubmit

**When**: User submits a prompt, before Claude processes it.

**No matcher**: Runs on all prompt submissions.

**Use cases**: Prompt validation, context injection, blocking sensitive inputs.

#### PreToolUse

**When**: After Claude creates tool parameters, before the tool executes.

**Matchers** (tool names, case-sensitive, supports regex):
- `Bash` - Shell commands
- `Write` - File writing
- `Edit` - File editing
- `Read` - File reading
- `Glob` - File pattern matching
- `Grep` - Content search
- `WebFetch`, `WebSearch` - Web operations
- `Task` - Subagent tasks
- `mcp__<server>__<tool>` - MCP tools
- `*` or `""` - Match all tools

**Use cases**: Blocking destructive commands, auto-approving safe operations, modifying tool inputs.

#### PermissionRequest

**When**: User is shown a permission dialog.

**Matchers**: Same as PreToolUse.

**Use cases**: Auto-allowing or auto-denying permission requests programmatically.

#### PostToolUse

**When**: Immediately after a tool completes successfully.

**Matchers**: Same as PreToolUse.

**Use cases**: Auto-formatting files, running linters, logging, providing feedback to Claude.

#### PostToolUseFailure

**When**: After a tool fails.

**Matchers**: Same as PreToolUse.

**Use cases**: Error analysis, failure logging.

#### SubagentStart

**When**: A subagent is spawned.

**No matcher**: Runs for all subagent starts.

**Use cases**: Detecting plan agents, logging subagent activity.

#### SubagentStop

**When**: A subagent finishes its work.

**No matcher**: Runs for all subagent completions.

**Use cases**: Validating subagent output, forcing continued work if tasks incomplete.

#### Stop

**When**: Main Claude Code agent finishes responding. Does NOT run on user interrupts.

**No matcher**: Runs on all stops.

**Use cases**: Intelligent continuation decisions, task completeness validation.

#### PreCompact

**When**: Before context compaction occurs.

**Matchers**: `manual` (from `/compact`), `auto` (from auto-compact).

**Use cases**: Injecting context preservation instructions.

#### Notification

**When**: Claude Code sends notifications.

**Matchers**: `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog`

**Use cases**: Custom notification routing (desktop notifications, Slack, etc.).

#### SessionEnd

**When**: Session terminates.

**No matcher**: Runs on all session ends.

**Reason values**: `clear`, `logout`, `prompt_input_exit`, `other`

**Use cases**: Cleanup, logging session statistics, saving state.

---

## 3. Hook Input Format

All hooks receive JSON data via stdin. Every event includes common fields plus event-specific data.

### Common Fields (All Events)

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../session-id.jsonl",
  "cwd": "/Users/project-dir",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse"
}
```

| Field             | Type   | Description                                                                     |
|-------------------|--------|---------------------------------------------------------------------------------|
| `session_id`      | string | Unique session identifier                                                       |
| `transcript_path` | string | Path to conversation JSON log                                                   |
| `cwd`             | string | Current working directory when hook is invoked                                  |
| `permission_mode` | string | Current mode: `"default"`, `"plan"`, `"acceptEdits"`, `"dontAsk"`, `"bypassPermissions"` |
| `hook_event_name` | string | Event type name                                                                 |

### Event-Specific Fields

#### PreToolUse

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "git push --force",
    "description": "Force push to remote",
    "timeout": 120000,
    "run_in_background": false
  },
  "tool_use_id": "toolu_01ABC123..."
}
```

**tool_input varies by tool:**

| Tool    | Key Fields                                              |
|---------|---------------------------------------------------------|
| `Bash`  | `command`, `description`, `timeout`, `run_in_background` |
| `Write` | `file_path`, `content`                                  |
| `Edit`  | `file_path`, `old_string`, `new_string`, `replace_all`  |
| `Read`  | `file_path`, `offset`, `limit`                          |

#### PostToolUse

Same as PreToolUse plus `tool_response`:

```json
{
  "hook_event_name": "PostToolUse",
  "tool_name": "Write",
  "tool_input": { "file_path": "/path/to/file.txt", "content": "..." },
  "tool_response": { "filePath": "/path/to/file.txt", "success": true },
  "tool_use_id": "toolu_01ABC123..."
}
```

#### UserPromptSubmit

```json
{
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Write a function to calculate factorial"
}
```

#### Stop

```json
{
  "hook_event_name": "Stop",
  "stop_hook_active": true
}
```

`stop_hook_active` is `true` when Claude is already continuing due to a previous Stop hook. **Check this to prevent infinite loops.**

#### SubagentStop

```json
{
  "hook_event_name": "SubagentStop",
  "stop_hook_active": false,
  "agent_id": "def456",
  "agent_transcript_path": "~/.claude/projects/.../abc123/subagents/agent-def456.jsonl"
}
```

#### SubagentStart

```json
{
  "hook_event_name": "SubagentStart",
  "agent_id": "agent-abc123",
  "agent_type": "Explore"
}
```

`agent_type` values include built-in agents (`"Bash"`, `"Explore"`, `"Plan"`) or custom agent names.

#### SessionStart

```json
{
  "hook_event_name": "SessionStart",
  "source": "startup",
  "model": "claude-sonnet-4-20250514"
}
```

`source` values: `"startup"`, `"resume"`, `"clear"`, `"compact"`. If started with `claude --agent <name>`, includes `agent_type`.

#### SessionEnd

```json
{
  "hook_event_name": "SessionEnd",
  "reason": "exit"
}
```

`reason` values: `"clear"`, `"logout"`, `"prompt_input_exit"`, `"other"`

#### Notification

```json
{
  "hook_event_name": "Notification",
  "message": "Claude needs your permission to use Bash",
  "notification_type": "permission_prompt"
}
```

#### PreCompact

```json
{
  "hook_event_name": "PreCompact",
  "trigger": "manual",
  "custom_instructions": ""
}
```

#### Setup

```json
{
  "hook_event_name": "Setup",
  "trigger": "init"
}
```

`trigger` values: `"init"`, `"maintenance"`

### Capturing Real Input Formats

**CRITICAL**: Never assume hook input formats. Always capture real events first.

Use the project's debug tool:

```bash
./scripts/debug_hooks.sh start "Describe your test scenario"
# Perform actions in Claude Code...
./scripts/debug_hooks.sh stop
```

Logs are saved to `/tmp/hook_debug_TIMESTAMP.log`. See `/workspace/CLAUDE/DEBUGGING_HOOKS.md` for the complete introspection workflow.

---

## 4. Hook Output Format

Hooks communicate back to Claude Code through two mechanisms: exit codes and JSON output.

### Exit Code Protocol

| Exit Code | Meaning                | stdout behavior                           | stderr behavior                    |
|-----------|------------------------|-------------------------------------------|------------------------------------|
| **0**     | Success                | Parsed as JSON if valid; context for some events | Ignored                       |
| **2**     | Blocking error         | **Ignored** (JSON not processed)          | Used as error message, fed to Claude |
| **Other** | Non-blocking error     | Ignored                                   | Shown to user in verbose mode      |

**Exit code 2 behavior by event:**

| Event             | Effect                                           |
|-------------------|--------------------------------------------------|
| `PreToolUse`      | Blocks tool call, stderr shown to Claude         |
| `PermissionRequest` | Denies permission, stderr shown to Claude      |
| `PostToolUse`     | Shows stderr to Claude (tool already ran)        |
| `UserPromptSubmit`| Blocks prompt, erases it, stderr shown to user   |
| `Stop`            | Blocks stopping, stderr shown to Claude          |
| `SubagentStop`    | Blocks stopping, stderr shown to subagent        |
| `Notification`    | Shows stderr to user only                        |
| `SessionStart`    | Shows stderr to user only                        |
| `SessionEnd`      | Shows stderr to user only                        |

### JSON Output (Exit Code 0 Only)

#### Common JSON Fields

```json
{
  "continue": true,
  "stopReason": "Reason shown to user when continue=false",
  "suppressOutput": false,
  "systemMessage": "Warning shown to the user"
}
```

- `continue: false` stops Claude entirely (takes precedence over all other decisions)
- `stopReason` accompanies `continue: false`; shown to user, NOT to Claude

#### PreToolUse Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "permissionDecisionReason": "Auto-approved: safe operation",
    "updatedInput": {
      "command": "modified command"
    },
    "additionalContext": "Extra info for Claude"
  }
}
```

| Decision  | Effect                                              |
|-----------|-----------------------------------------------------|
| `"allow"` | Bypasses permission system. Reason shown to user only |
| `"deny"`  | Blocks tool call. Reason shown to Claude            |
| `"ask"`   | Shows confirmation UI. Reason shown to user only    |

`updatedInput` modifies tool parameters before execution. `additionalContext` adds information to Claude's context.

#### PermissionRequest Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow",
      "updatedInput": { "command": "npm run lint" }
    }
  }
}
```

For `"deny"`: include `"message"` (tells model why) and optional `"interrupt"` boolean (stops Claude).

#### PostToolUse Decision Control

```json
{
  "decision": "block",
  "reason": "Linting errors detected",
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "Additional info for Claude"
  }
}
```

`"block"` automatically prompts Claude with the reason. Omitting `decision` does nothing.

#### UserPromptSubmit Decision Control

Two ways to add context (exit code 0):
1. **Plain text stdout** -- simplest approach
2. **JSON with `additionalContext`** -- more structured

```json
{
  "decision": "block",
  "reason": "Security violation: prompt contains secrets",
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "Additional context string"
  }
}
```

#### Stop / SubagentStop Decision Control

```json
{
  "decision": "block",
  "reason": "Tasks are not complete. Please finish X before stopping."
}
```

`"block"` prevents stopping; `reason` is **required** so Claude knows what to do.

#### SessionStart Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Current sprint: implement feature X"
  }
}
```

Multiple hooks' `additionalContext` values are concatenated.

#### Setup Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "Setup",
    "additionalContext": "Repository initialized with custom configuration"
  }
}
```

---

## 5. Handler Development

This section covers handler development within the hooks daemon architecture used by this project.

### Architecture Overview

```
Claude Code CLI
    |
    v (bash script)
Unix Socket IPC
    |
    v
Daemon Server
    |
    v
FrontController
    |
    v
EventRouter --> HandlerChain --> Handler.matches() --> Handler.handle()
                                     |
                                     v
                                 HookResult
```

### Handler Skeleton

```python
from claude_code_hooks_daemon.core import Handler, HookResult

class MyHandler(Handler):
    """One-line description of what this handler does."""

    def __init__(self) -> None:
        super().__init__(
            name="my-handler",       # Unique, kebab-case
            priority=50,             # Lower runs first (5-60)
            terminal=True,           # Stop dispatch chain after match?
            tags=["safety", "git"],  # Categorization tags
        )

    def matches(self, hook_input: dict) -> bool:
        """Return True if this handler should execute."""
        return hook_input.get("tool_name") == "Bash"

    def handle(self, hook_input: dict) -> HookResult:
        """Execute handler logic, return result."""
        return HookResult(
            decision="deny",
            reason="Blocked: clear explanation with alternatives"
        )
```

### Priority Ranges

| Range | Category     | Examples                                    |
|-------|-------------|---------------------------------------------|
| 5-9   | Architecture | Controller pattern enforcement              |
| 10-20 | Safety       | Destructive git, sed blocker, data loss     |
| 21-30 | Code Quality | ESLint disable, TypeScript errors           |
| 31-45 | Workflow     | TDD enforcement, plan validation            |
| 46-60 | Advisory     | British English warnings, suggestions       |

**Lower priority number = runs first.**

### Terminal vs Non-Terminal

**Terminal (`terminal=True`)**: Stops the dispatch chain. The decision becomes final. Use when you need to **block or enforce**.

**Non-Terminal (`terminal=False`)**: Allows subsequent handlers to run. Decision is ignored (always treated as allow). Context is accumulated. Use when you want to **warn or guide**.

### HookResult Options

```python
# Silent allow
HookResult(decision="allow")

# Allow with context (injected into Claude's awareness)
HookResult(decision="allow", context="Reminder: update docs")

# Allow with guidance
HookResult(decision="allow", guidance="Consider using X instead")

# Deny (block the operation)
HookResult(decision="deny", reason="Clear explanation + alternatives")

# Ask (request user approval)
HookResult(decision="ask", reason="This requires confirmation because...")
```

### Utility Functions

```python
from claude_code_hooks_daemon.core.utils import (
    get_bash_command,   # Extract command from Bash tool input
    get_file_path,      # Extract file path from Write/Edit tool input
    get_file_content,   # Extract content from Write tool input
)
```

### Testing Approach

**Debug first, develop second.** Always:

1. Run `./scripts/debug_hooks.sh start "scenario"` to capture real events
2. Analyze logs to understand event flow and data
3. Write failing tests (TDD red phase)
4. Implement handler (TDD green phase)
5. Refactor
6. Run full QA: `./scripts/qa/run_all.sh`
7. Debug again to verify handler intercepts correctly

See `/workspace/CLAUDE/DEBUGGING_HOOKS.md` for the complete introspection guide and `/workspace/CLAUDE/HANDLER_DEVELOPMENT.md` for the full handler creation guide.

---

## 6. Configuration

### Settings File Locations

Hooks are configured in Claude Code settings files (JSON):

| File | Scope |
|------|-------|
| `~/.claude/settings.json` | User (all projects) |
| `.claude/settings.json` | Project (committed) |
| `.claude/settings.local.json` | Local project (not committed) |
| Managed policy settings | Enterprise |

### Configuration Structure

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/script.sh",
            "timeout": 60
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/validator.py"
          }
        ]
      }
    ]
  }
}
```

- **matcher**: Case-sensitive, supports regex (`Edit|Write`, `mcp__.*`), `*` for all
- **type**: `"command"` (bash) or `"prompt"` (LLM-based, for Stop/SubagentStop)
- **timeout**: Seconds (default 60)

### MCP Tool Naming in Matchers

MCP tools follow the pattern `mcp__<server>__<tool>`:

```json
{
  "matcher": "mcp__memory__.*",
  "hooks": [{ "type": "command", "command": "..." }]
}
```

### Environment Variables

| Variable | Available In | Description |
|----------|-------------|-------------|
| `CLAUDE_PROJECT_DIR` | All hooks | Absolute path to project root |
| `CLAUDE_ENV_FILE` | SessionStart, Setup only | File path for persisting env vars |
| `CLAUDE_CODE_REMOTE` | All hooks | `"true"` if remote/web, empty if local |
| `CLAUDE_PLUGIN_ROOT` | Plugin hooks only | Absolute path to plugin directory |

### Hooks in Skills and Agents

Skills and subagents can define scoped hooks in their frontmatter:

```yaml
---
name: secure-operations
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/security-check.sh"
---
```

Supported events for skill/agent hooks: `PreToolUse`, `PostToolUse`, `Stop`. Skills also support `once: true` to run only once per session.

---

## 7. Critical Guidelines

### Claude Code CLI Is the Source of Truth

The Claude Code CLI defines the hook input/output formats. These formats can change between versions. **Never assume formats based on documentation alone** -- always validate against real events.

### Always Debug Real Events Before Writing Tests

```bash
./scripts/debug_hooks.sh start "Testing scenario X"
# Perform the scenario in Claude Code
./scripts/debug_hooks.sh stop
```

This captures the **exact** JSON that Claude Code sends. Your handler tests should use data structures that match these real events.

### Test Expectations Can Be Wrong

If a test expects `tool_output` but Claude Code sends `tool_response`, the test is wrong, not the CLI. When tests fail against real events, **fix the tests**, not the handler.

### Hook Execution Details

- **Timeout**: 60 seconds default, configurable per command
- **Parallelization**: All matching hooks run in parallel
- **Deduplication**: Identical hook commands are deduplicated
- **Input**: JSON via stdin
- **Configuration safety**: Hook changes require review via `/hooks` menu; changes don't take effect mid-session

### Security Considerations

1. **Validate and sanitize inputs** -- never trust input data blindly
2. **Always quote shell variables** -- use `"$VAR"` not `$VAR`
3. **Block path traversal** -- check for `..` in file paths
4. **Use absolute paths** -- specify full paths for scripts
5. **Skip sensitive files** -- avoid `.env`, `.git/`, keys
6. Hooks execute with your environment's credentials -- treat hook code with the same care as any privileged script

### Debugging

1. Run `/hooks` in Claude Code to verify registration
2. Use `claude --debug` for detailed execution logs
3. Test hook commands manually: `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | ./your-hook.sh`
4. Check permissions: scripts must be executable (`chmod +x`)

---

## 8. Reference Links

- [Hooks Reference (official)](https://code.claude.com/docs/en/hooks.md) -- Complete CLI hook specification
- [Hooks Guide (official)](https://code.claude.com/docs/en/hooks-guide.md) -- Quickstart and examples
- [Settings Reference](https://code.claude.com/docs/en/settings.md) -- Configuration file details
- `/workspace/CLAUDE/DEBUGGING_HOOKS.md` -- Debug tool for capturing event flows
- `/workspace/CLAUDE/HANDLER_DEVELOPMENT.md` -- Handler creation guide for this project
- `/workspace/CLAUDE/ARCHITECTURE.md` -- System architecture
