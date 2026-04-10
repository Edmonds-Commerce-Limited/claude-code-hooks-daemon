# Debugging with Claude Code Transcripts

**Purpose**: Investigate bugs and unexpected behaviour by analysing Claude Code session transcripts. This is the definitive technique for post-mortem debugging when live reproduction is difficult or impossible.

## When to Use This

- Bug reports where the cause is unclear (daemon vs Claude Code vs environment)
- Investigating tool call failures, empty responses, or unexpected behaviour
- Verifying whether hooks daemon handlers interfered with a tool call
- Understanding exact event timing and sequencing
- Debugging issues that only occur in specific environments or sessions

## Transcript Format

Claude Code stores session transcripts as JSONL files (one JSON object per line). Each line is an event:

| Field             | Description                                           |
| ----------------- | ----------------------------------------------------- |
| `type`            | Event type: `"assistant"`, `"user"`, `"progress"`     |
| `message.role`    | `"assistant"` (tool calls) or `"user"` (tool results) |
| `message.content` | Array of content blocks (text, tool_use, tool_result) |
| `uuid`            | Unique event ID                                       |
| `parentUuid`      | Links events in a chain                               |
| `timestamp`       | ISO 8601 timestamp                                    |
| `sessionId`       | Session identifier                                    |
| `version`         | Claude Code CLI version                               |

### Tool Call Events (assistant)

```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_XXXX",
        "name": "ToolName",
        "input": { ... }
      }
    ]
  }
}
```

### Tool Result Events (user)

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_XXXX",
        "content": "result text"
      }
    ]
  },
  "toolUseResult": { ... }
}
```

### Hook Progress Events

```json
{
  "type": "progress",
  "data": {
    "type": "hook_progress",
    "hookEvent": "PreToolUse",
    "hookName": "PreToolUse:ToolName"
  },
  "toolUseID": "toolu_XXXX"
}
```

## Accessing Transcripts

### From the Current Session

Transcripts for the current project are at:

```
~/.claude/projects/<encoded-project-path>/<session-id>.jsonl
```

The `sessions-index.json` in the same directory lists all sessions with summaries.

### From Another Project (CCY Containers)

When using CCY containers (Podman-based YOLO environments from [fedora-desktop](https://github.com/LongTermSupport/fedora-desktop/)), Claude session data is stored in the project's `.claude/ccy/` directory.

To access transcripts from another project inside your current container:

```bash
# Copy from another project's CCY session storage into untracked/
cp -r ../../other-project/.claude/ccy/projects ./untracked/other-project-claude-projects

# The transcripts are now at:
# untracked/other-project-claude-projects/-workspace/<session-id>.jsonl
```

**Important**: Copy into `untracked/` so transcripts are not committed to the repo.

### From Standard Claude Code (Non-CCY)

```bash
# On the host machine, transcripts are at:
~/.claude/projects/<encoded-path>/<session-id>.jsonl

# Copy into container's untracked/ for analysis
cp -r ~/.claude/projects/-path-to-project/ /path/to/workspace/untracked/debug-transcripts/
```

## Debugging Workflow

### Step 1: Find the Relevant Session

```bash
# List sessions with summaries
cat untracked/debug-transcripts/-workspace/sessions-index.json | jq '.entries[] | {id: .sessionId, summary: .summary, date: .modified}'

# Or search for specific tool calls across all sessions
grep -rl '"name":"ToolName"' untracked/debug-transcripts/-workspace/*.jsonl
```

### Step 2: Search for the Event of Interest

```bash
# Find specific tool calls
grep '"name":"AskUserQuestion"' session.jsonl

# Find tool results by tool_use_id
grep 'toolu_XXXX' session.jsonl

# Find hook progress events
grep 'hook_progress' session.jsonl

# Find error responses
grep -i '"error"' session.jsonl
```

### Step 3: Analyse the Event Chain

For a tool call, there are typically 3-4 events in sequence:

1. **Assistant tool_use** — Claude calls the tool
2. **Hook progress (PreToolUse)** — Daemon's PreToolUse hook fires
3. **Hook progress (PostToolUse)** — Daemon's PostToolUse hook fires
4. **User tool_result** — The result returned to Claude

Extract all events for a specific tool call:

```bash
grep 'toolu_XXXX' session.jsonl
```

### Step 4: Check Timing

Compare timestamps between events to identify auto-dismissals or delays:

```
PreToolUse:  16:52:15.484
PostToolUse: 16:52:15.590  (106ms later)
Tool result: 16:52:15.590  (same as PostToolUse)
```

**Key indicators:**

- **< 200ms total** = Tool was auto-dismissed (user never saw it)
- **Seconds to minutes** = Normal user interaction
- **Large gap before PostToolUse** = Tool execution took time (normal for Bash)

### Step 5: Check the Tool Result

The `toolUseResult` field contains the raw structured result:

```bash
# Extract the toolUseResult for a specific tool call
grep 'toolu_XXXX' session.jsonl | grep '"type":"user"' | jq '.toolUseResult'
```

Look for:

- Empty `answers: {}` on AskUserQuestion = auto-dismissed
- Error messages in tool_result content
- Missing or unexpected fields

### Step 6: Determine the Cause

| Finding                    | Likely Cause                                      |
| -------------------------- | ------------------------------------------------- |
| PreToolUse returned deny   | Hooks daemon handler blocked it                   |
| Tool result empty, < 200ms | Claude Code auto-dismissed (YOLO/permission mode) |
| Tool result has error      | Tool execution failed                             |
| No hook_progress events    | Hooks not configured for this event type          |
| PostToolUse has advisory   | Daemon injected context (non-blocking)            |

## Worked Example: AskUserQuestion Empty Answers

### The Bug

AskUserQuestion returned `answers: {}` with the message `"User has answered your questions: ."` — the user never saw the prompt.

### Investigation

**1. Found the session** via sessions-index.json search

**2. Searched for the tool call:**

```bash
grep '"name":"AskUserQuestion"' session.jsonl
```

**3. Extracted the full event chain** by tool_use_id:

```bash
grep 'toolu_014RfJnNQtLzVAPVqQCC6Kcq' session.jsonl
```

**4. Analysed timing:**

- PreToolUse → PostToolUse: **106ms**
- Far too fast for user interaction = auto-dismissed

**5. Checked the tool result:**

```json
{
  "answers": {},
  "questions": [...]
}
```

Empty answers confirmed — user never saw the prompt.

**6. Checked caller context:**

- `caller.type: "direct"` — main thread, not sub-agent
- Claude Code version: 2.1.63
- PreToolUse hook allowed the call (daemon did not block)

**7. Reproduction test** in current session (v2.1.76):

- AskUserQuestion worked correctly with full UI and captured answers
- Same YOLO mode, same container type

### Conclusion

Claude Code v2.1.63 auto-dismissed AskUserQuestion in YOLO mode. The daemon was not involved — hooks processed correctly. Issue tracked in GitHub issue #26.

## Tips

- **Always check `caller.type`** — `"direct"` = main thread, `"subagent"` = spawned agent. Sub-agents may handle tools differently.
- **Always check `version`** — behaviour can change between Claude Code versions.
- **Compare working vs broken sessions** — same tool, different outcomes. Timestamps and version differences reveal the cause.
- **Check `permission_mode`** in hook_input data — different modes can cause different tool behaviours.
- **Sanitise before sharing** — transcripts contain file paths, code, and potentially sensitive data. Strip identifying information before posting to public issues.

## Related

- [DEBUGGING_HOOKS.md](DEBUGGING_HOOKS.md) — Live hook event debugging with `debug_hooks.sh`
- [GitHub Issue #26](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/26) — AskUserQuestion auto-dismissal bug
