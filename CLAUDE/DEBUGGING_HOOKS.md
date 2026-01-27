# Debugging Hooks: Introspecting Event Flow

**Critical for handler development**: This tool lets you capture exact hook event sequences for any Claude Code scenario, enabling surgical precision when deciding which events to hook and what data to inspect.

## Why This Matters

Before writing handlers, you need to understand:
- **Which events fire** for a given Claude Code workflow (planning mode, git operations, file edits, etc.)
- **What order** events fire in
- **What data** is available in each event's `hook_input`
- **How events relate** (e.g., PreToolUse → PostToolUse → SubagentStop chains)

Without introspection, you're guessing. With it, you're surgically precise.

## The Debug Tool

**Location**: `scripts/debug_hooks.sh`

**Purpose**: Injects boundary markers into daemon logs, captures all DEBUG-level logs between markers, filters to only the debug session.

### Usage

```bash
# 1. Start debug session with descriptive message
./scripts/debug_hooks.sh start "Testing planning mode workflow"

# 2. Perform your test scenario in Claude Code
# Example: Enter planning mode, create a plan, exit planning mode

# 3. Stop session - automatically dumps filtered logs
./scripts/debug_hooks.sh stop
```

### Output

Logs are saved to `/tmp/hook_debug_TIMESTAMP.log` and displayed in terminal.

Example output:
```
2026-01-27 04:37:27,189 [INFO] === START BOUNDARY: Testing planning mode ===
2026-01-27 04:37:27,475 [DEBUG] Routing PreToolUse event to chain with 17 handlers
2026-01-27 04:37:27,832 [DEBUG] Routing PostToolUse event to chain with 4 handlers
2026-01-27 04:37:32,469 [DEBUG] Routing SubagentStart event
2026-01-27 04:37:34,040 [INFO] === END BOUNDARY ===
```

## Workflow: From Scenario to Handler

### Step 1: Identify Scenario

Examples:
- "Entering planning mode"
- "Creating git commits"
- "Running tests after code changes"
- "User says 'continue'"

### Step 2: Capture Event Flow

```bash
./scripts/debug_hooks.sh start "Scenario: User enters planning mode"

# In Claude Code session:
# - User types request that triggers EnterPlanMode
# - Claude enters planning mode
# - Claude exits planning mode

./scripts/debug_hooks.sh stop
```

### Step 3: Analyze Logs

Look for:

1. **Event Types**: Which events fired?
   ```
   PreToolUse event to chain    # Tool about to execute
   PostToolUse event to chain   # Tool finished
   SubagentStart event          # Subagent spawned
   SubagentStop event           # Subagent completed
   ```

2. **Tool Names**: What tools were called?
   ```
   [DEBUG] Handler checking tool: EnterPlanMode
   [DEBUG] Handler checking tool: ExitPlanMode
   [DEBUG] Handler checking tool: Read
   ```

3. **Event Data**: What's in `hook_input`?
   ```
   [DEBUG] hook_input: {
     "tool_name": "EnterPlanMode",
     "tool_input": {...},
     "context": {...}
   }
   ```

4. **Handler Execution**: Which handlers ran?
   ```
   [DEBUG] Handler destructive_git matched event
   [DEBUG] Handler tdd_enforcement matched event
   ```

### Step 4: Design Handler

Based on logs, decide:

**Which event type?**
- `PreToolUse` - Before tool executes (can block/modify)
- `PostToolUse` - After tool succeeds (can validate/enhance)
- `SubagentStop` - When subagent completes (can remind/report)
- `UserPromptSubmit` - User input (can auto-continue/inject context)

**What to match on?**
```python
def matches(self, hook_input: dict) -> bool:
    # From logs, you know exactly what's in hook_input
    tool_name = hook_input.get("tool_name")
    tool_input = hook_input.get("tool_input", {})

    # Match on specific tool
    if tool_name == "EnterPlanMode":
        return True

    # Match on tool input data
    if tool_name == "Bash" and "git commit" in tool_input.get("command", ""):
        return True

    return False
```

**What action to take?**
```python
def handle(self, hook_input: dict) -> HookResult:
    # From logs, you know what data is available
    tool_input = hook_input.get("tool_input", {})

    # Block action
    return HookResult(
        decision="deny",
        reason="Blocked because X"
    )

    # Modify action
    return HookResult(
        decision="allow",
        modified_input={"command": "improved command"}
    )

    # Advisory warning
    return HookResult(
        decision="allow",
        context="⚠️ Warning: this might..."
    )
```

## Example: Debugging Planning Mode

### Scenario
We want to inject custom context when Claude enters planning mode.

### Capture
```bash
./scripts/debug_hooks.sh start "Planning mode entry and exit"

# In Claude Code: Trigger planning mode
# User: "Plan how to implement feature X"

./scripts/debug_hooks.sh stop
```

### Analyze Output
```
[DEBUG] Routing PreToolUse event to chain with 17 handlers
[DEBUG] Handler checking tool: EnterPlanMode
[DEBUG] hook_input: {
  "tool_name": "EnterPlanMode",
  "tool_input": {},
  "context": {...}
}
[DEBUG] Handler matched: false (no handlers for EnterPlanMode)
[DEBUG] Request processed in 0.41ms

[DEBUG] Routing SubagentStart event to chain with 2 handlers
[DEBUG] hook_input: {
  "agent_type": "Plan",
  "prompt": "Plan how to implement feature X",
  ...
}

[DEBUG] Routing SubagentStop event to chain with 3 handlers
[DEBUG] hook_input: {
  "agent_type": "Plan",
  "result": "...",
  ...
}
```

### Insights
1. **EnterPlanMode fires PreToolUse** - we can intercept before planning starts
2. **SubagentStart fires with agent_type="Plan"** - we can detect plan agent spawning
3. **SubagentStop fires when plan completes** - we can remind/validate after planning

### Handler Decision
```python
# Option 1: Intercept before planning starts (PreToolUse)
class PlanningModePrep(Handler):
    def __init__(self) -> None:
        super().__init__(name="planning-mode-prep", priority=30, terminal=False)

    def matches(self, hook_input: dict) -> bool:
        return hook_input.get("tool_name") == "EnterPlanMode"

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(
            decision="allow",
            context="📋 Entering planning mode. Remember to:\n"
                   "- Consider architecture trade-offs\n"
                   "- Plan for testability"
        )

# Option 2: Detect plan agent (SubagentStart)
class PlanAgentDetector(Handler):
    def __init__(self) -> None:
        super().__init__(name="plan-agent-detector", priority=10, terminal=False)

    def matches(self, hook_input: dict) -> bool:
        return hook_input.get("agent_type") == "Plan"

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(
            decision="allow",
            context="🎯 Plan agent started - architectural planning mode active"
        )

# Option 3: Validate after planning (SubagentStop)
class PlanValidator(Handler):
    def __init__(self) -> None:
        super().__init__(name="plan-validator", priority=20, terminal=False)

    def matches(self, hook_input: dict) -> bool:
        return hook_input.get("agent_type") == "Plan"

    def handle(self, hook_input: dict) -> HookResult:
        result = hook_input.get("result", "")

        # Check if plan mentions tests
        if "test" not in result.lower():
            return HookResult(
                decision="allow",
                context="⚠️ Plan doesn't mention testing strategy"
            )

        return HookResult(decision="allow")
```

## Common Scenarios to Debug

### Git Operations
```bash
./scripts/debug_hooks.sh start "Git commit workflow"
# Perform: git add, git commit, git push
./scripts/debug_hooks.sh stop
```

Look for: `Bash` tool with `git` commands in PreToolUse events

### File Editing
```bash
./scripts/debug_hooks.sh start "File edit and validation"
# Perform: Edit file, run linter
./scripts/debug_hooks.sh stop
```

Look for: `Edit`/`Write` tools in PreToolUse, validation in PostToolUse

### Test Running
```bash
./scripts/debug_hooks.sh start "Test execution after code change"
# Perform: Edit code, run tests
./scripts/debug_hooks.sh stop
```

Look for: `Bash` tool with test commands, timing between Edit and Bash

### User Prompts
```bash
./scripts/debug_hooks.sh start "User types 'continue'"
# Type: continue
./scripts/debug_hooks.sh stop
```

Look for: UserPromptSubmit event with prompt text

## Tips

### 1. Be Specific with Boundary Messages
```bash
# Good
./scripts/debug_hooks.sh start "Testing EnterPlanMode → ExitPlanMode sequence"

# Bad
./scripts/debug_hooks.sh start "test"
```

### 2. Keep Test Scenarios Simple
Capture one workflow at a time. Complex scenarios create noisy logs.

### 3. Look for Patterns, Not One-Offs
If you see an event fire once, test again to confirm it's consistent.

### 4. Check Multiple Event Types
Don't just look at PreToolUse - SubagentStart/Stop might be more appropriate.

### 5. Save Logs for Reference
```bash
./scripts/debug_hooks.sh stop > scenarios/planning_mode_flow.log
```

Build a library of event flow logs for common scenarios.

## Advanced: Comparing Scenarios

```bash
# Scenario A: Normal git commit
./scripts/debug_hooks.sh start "Normal git commit"
# git commit -m "message"
./scripts/debug_hooks.sh stop > /tmp/normal_commit.log

# Scenario B: Git commit with pre-commit hook failure
./scripts/debug_hooks.sh start "Git commit with hook failure"
# git commit (fails pre-commit hook)
./scripts/debug_hooks.sh stop > /tmp/failed_commit.log

# Compare
diff /tmp/normal_commit.log /tmp/failed_commit.log
```

Differences reveal when/how to detect failures and respond.

## Technical Details

### How It Works

1. **START**:
   - Enables DEBUG logging in config
   - Restarts daemon with DEBUG level
   - Injects `=== START BOUNDARY: message ===` via `log_marker` system action

2. **During Session**:
   - All hook events logged at DEBUG level
   - Full handler dispatch chains logged
   - Tool names, inputs, and results captured

3. **STOP**:
   - Injects `=== END BOUNDARY ===` marker
   - Retrieves all DEBUG logs from memory buffer
   - Filters to only logs between boundaries using awk
   - Restores INFO logging
   - Restarts daemon

### Log Format

```
TIMESTAMP [LEVEL] module: message

2026-01-27 04:37:27,189 [INFO] claude_code_hooks_daemon.daemon.server: === START BOUNDARY ===
2026-01-27 04:37:27,475 [DEBUG] claude_code_hooks_daemon.core.router: Routing PreToolUse event
```

### Limitations

- **Memory buffer**: Only last 1000 log entries kept (configurable in `MemoryLogHandler`)
- **Session duration**: Long sessions might exceed buffer, losing early logs
- **Daemon restart**: Restarts daemon at start/stop (brief interruption)

### Troubleshooting

**"Daemon socket not found"**
```bash
# Check daemon is running
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
```

**"No logs in buffer"**
- Session was too short (daemon hadn't processed events yet)
- Daemon was restarted since events fired
- Try longer/more active test scenario

**"Coverage failure" when running tests**
```bash
# Debug script doesn't affect coverage
# This is expected if you only ran log_marker tests
./scripts/qa/run_tests.sh  # Run full test suite
```

## Integration with Handler Development

See [HANDLER_DEVELOPMENT.md](./HANDLER_DEVELOPMENT.md) for full handler creation guide.

**Recommended workflow:**
1. Identify scenario (e.g., "enforce TDD")
2. **Debug the scenario** (this doc)
3. Analyze event flow
4. Write tests (TDD)
5. Implement handler
6. **Debug the handler** to verify it intercepts correctly
7. Iterate

## Related Documentation

- [HANDLER_DEVELOPMENT.md](./HANDLER_DEVELOPMENT.md) - Complete handler creation guide
- [ARCHITECTURE.md](./ARCHITECTURE.md) - System design and event flow
- [../README.md](../README.md) - Installation and usage

## Contributing Debug Scenarios

If you capture useful event flow logs for common scenarios, please contribute them:

1. Create `CLAUDE/DEBUG_SCENARIOS/` directory
2. Save logs: `scenario_name.log`
3. Add README explaining scenario
4. Submit PR

Example scenarios to capture:
- Planning mode (enter/exit)
- Git workflows (commit, push, rebase)
- Test execution patterns
- File editing chains (Edit → Format → Lint → Test)
- Error recovery (failed commands, retries)
- Subagent spawning (different agent types)
