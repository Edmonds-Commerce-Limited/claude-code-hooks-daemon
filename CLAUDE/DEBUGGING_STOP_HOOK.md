# Debugging Stop Hook Failures

**Purpose**: Diagnose and fix dogfooding issues where the stop hook fails to block Claude from stopping when it should.

**When to use this guide**:

- Claude stops mid-task without a `STOPPING BECAUSE:` prefix and was not blocked
- You had to type "go" or "continue" manually to resume Claude
- `preventedContinuation: false` appears in a transcript when blocking was expected
- The stop hook was recently changed and may have regressed

**Related**: See `.claude/agents/transcript-inspector.md` for an agent that automates diagnosis.

---

## The Symptom

The canonical symptom of a broken stop hook is Claude stopping and waiting, forcing a manual "go" response. The transcript records this as:

```
stop_hook_summary: { preventedContinuation: false, level: "suggestion" }
...
user: "go"   ← manual resume, should never appear in a working session
```

A working stop hook produces:

```
stop_hook_summary: { preventedContinuation: true, level: "error" }
← Claude auto-continues, no user input needed
```

---

## The Stop Hook Chain

Understanding all layers is essential for isolating which layer is broken.

```
Claude Code wants to stop
        │
        ▼
[1] hook script: /workspace/.claude/hooks/stop
    Reads stdin (JSON from Claude Code)
    Wraps as: {"event":"Stop","hook_input":{...}}
    Sends to Unix socket via nc -U
        │
        ▼
[2] Daemon socket: /workspace/untracked/daemon-{hostname}.sock
    Receives {"event":"Stop","hook_input":{...}}
    Routes to FrontController(event_name="Stop")
        │
        ▼
[3] Handler chain (sorted by priority)
    AutoContinueStopHandler (priority 10, terminal=True)
      matches() → checks stop_hook_active, AskUserQuestion
      handle()  → branches on QA failure / STOPPING BECAUSE: / confirmation / default
        │
        ▼
[4] HookResult.to_json(event_name="Stop")
    DENY  → {"decision":"block","reason":"..."}
    ALLOW → {}
        │
        ▼
[5] Daemon writes JSON response to socket
    Hook script reads response from socket, writes to stdout
        │
        ▼
[6] Claude Code reads stdout from hook script
    {"decision":"block"} → preventedContinuation: true
    {} or missing        → preventedContinuation: false, level: "suggestion"
```

**Each layer can fail independently.** The diagnostic approach isolates them bottom-up.

---

## Transcript Data Model for Stop Events

Claude Code session transcripts are JSONL files at:

```
/root/.claude/projects/-workspace/<session-id>.jsonl
```

Find the current session transcript:

```bash
ls -t /root/.claude/projects/-workspace/*.jsonl | head -1
```

### Key Entry Types

#### Stop Hook Firing (`type=progress`)

```json
{
  "type": "progress",
  "data": {
    "type": "hook_progress",
    "hookEvent": "Stop",
    "hookName": "Stop"
  },
  "toolUseID": "toolu_..."
}
```

This confirms the hook was invoked. If this entry is absent, Claude Code never called the hook script (check `.claude/hooks-daemon.yaml` Stop event configuration).

#### Stop Hook Outcome (`subtype=stop_hook_summary`)

```json
{
  "type": "system",
  "subtype": "stop_hook_summary",
  "preventedContinuation": false,
  "level": "suggestion",
  "hasOutput": true,
  "hookErrors": []
}
```

This is the ground truth. Fields:

| Field                   | Meaning when broken                   | Meaning when working                            |
| ----------------------- | ------------------------------------- | ----------------------------------------------- |
| `preventedContinuation` | `false` — hook did not block          | `true` — hook blocked stop                      |
| `level`                 | `"suggestion"` — daemon returned `{}` | `"error"` or `"block"` — decision field present |
| `hasOutput`             | `false` — hook produced no output     | `true` — hook produced JSON                     |
| `hookErrors`            | Non-empty — hook script crashed       | `[]` — no errors                                |

**The key diagnostic combination**:

- `preventedContinuation: false` + `level: "suggestion"` + `hasOutput: true` = hook ran and returned `{}` (ALLOW). The daemon's `to_json()` produced an empty object. This means `HookResult` had `decision=ALLOW` and no context.
- `preventedContinuation: false` + `hasOutput: false` = hook script produced nothing. Either daemon was down or the script itself crashed.

#### Last Assistant Message (`type=assistant`)

```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      {"type": "text", "text": "I have completed the task..."}
    ]
  }
}
```

The `AutoContinueStopHandler` reads this via `TranscriptReader.get_last_assistant_text()`. The handler's Branch 2 looks for a `STOPPING BECAUSE:` prefix. Branch 3 looks for confirmation question patterns. Branch 4 (default) blocks everything else when `force_explanation=True`.

#### Manual Resume (broken stop hook symptom)

```json
{"type": "user", "message": {"role": "user", "content": "go"}}
```

If you see a bare `"go"` or `"continue"` user message immediately after a `stop_hook_summary`, the stop hook failed to block and a human had to intervene.

---

## Diagnostic Commands

### Find All Stop Outcomes in a Transcript

```python
import json

transcript = '/root/.claude/projects/-workspace/LATEST.jsonl'  # replace with actual path

with open(transcript) as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    try:
        e = json.loads(line)
    except json.JSONDecodeError:
        continue
    if e.get('subtype') == 'stop_hook_summary':
        print(i, e['preventedContinuation'], e.get('level'), e.get('hasOutput'))
```

### Test the Hook Script (Layer 1)

```bash
echo '{"hook_event_name":"Stop","stop_hook_active":false}' | /workspace/.claude/hooks/stop
```

Working output:

```json
{"decision":"block","reason":"You stopped without explaining why..."}
```

Broken outputs and their meanings:

- `{}` — hook script ran, daemon responded ALLOW
- *(no output)* — hook script crashed or daemon unreachable
- `{"error":"...","type":"hook_error"}` — daemon startup failed

### Test the Daemon Socket (Layer 2-5)

```bash
SOCK=$(ls /workspace/untracked/daemon-*.sock 2>/dev/null | head -1)
echo '{"event":"Stop","hook_input":{"hook_event_name":"Stop","stop_hook_active":false}}' \
    | nc -U "$SOCK"
```

Working output includes `"decision":"deny"` at the top level:

```json
{
  "result": {"decision":"deny","reason":"You stopped without explaining why...","context":[]},
  "timing_ms": 1.23,
  "handlers_matched": ["auto_continue_stop"]
}
```

If `handlers_matched` is empty (`[]`), the handler's `matches()` returned False for this input. Check `stop_hook_active` — if it is `true`, the re-entry guard is firing (correct behaviour). If it is `false`, there is a bug in `matches()`.

### Check the Daemon's Internal Log (Layer 3)

`AutoContinueStopHandler` writes a JSONL entry for every stop event it processes:

```bash
tail -10 /workspace/untracked/stop-events.jsonl
```

Each entry:

```json
{"timestamp":"2026-03-30T10:00:00+00:00","decision":"deny","reason_prefix":"You stopped without...","stop_hook_active":false}
```

Cross-reference with the transcript:

- Log entry with `decision: deny` but transcript shows `preventedContinuation: false` → daemon is blocking but the response is not reaching Claude Code. The hook script → socket pipe is broken.
- No log entry for a stop event that appears in transcript → handler never ran. Check daemon status.

---

## Common Root Causes

### 1. Daemon Not Running

```bash
/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
```

If not `RUNNING`, restart it:

```bash
/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

Then test the hook script again.

### 2. Re-Entry Guard Firing (`stop_hook_active: true`)

`AutoContinueStopHandler.matches()` returns `False` when `hook_input.get("stop_hook_active")` is truthy. Claude Code sets this field to `true` when it is processing the hook's block response (to prevent infinite loops).

This is **correct behaviour**. If you see it during normal operation (not during a stop-hook-triggered continuation), check whether something upstream is setting this field unexpectedly.

### 3. `force_explanation: false` in Config

Check `.claude/hooks-daemon.yaml`:

```yaml
handlers:
  stop:
    auto_continue_stop:
      options:
        force_explanation: false   # ← Branch 4 will ALLOW instead of DENY
```

If `force_explanation` is `false`, the handler allows stops that do not match any other branch. Set to `true` (the default) to require `STOPPING BECAUSE:` prefixes.

### 4. `to_json()` Event Name Mismatch

`HookResult.to_json(event_name)` uses exact string matching. The Stop-specific path is:

```python
if event_name in ("Stop", "SubagentStop"):
    return self._format_stop_response()
```

`_format_stop_response()` only includes `{"decision":"block","reason":"..."}` when `self.decision == Decision.DENY`. For ALLOW it returns `{}`.

If the `FrontController` is constructed with an incorrect `event_name` string (e.g. `"stop"` lowercase), the response falls through to `_format_system_message_response()` which produces `{"systemMessage":"..."}` instead of `{"decision":"block"}`. Claude Code does not recognise `systemMessage` as a blocking signal on Stop events.

To verify: check the `hooks/stop.py` entry point which constructs `FrontController(event_name="Stop")` — the capital S is required.

### 5. ALLOW Decision Returned by Handler

If the socket test (Layer 2-5) shows `handlers_matched: ["auto_continue_stop"]` but `decision: allow`, the handler ran but returned ALLOW. This happens when:

- **Branch 2 fires**: Last assistant message starts with `STOPPING BECAUSE:` — this is correct, the handler intentionally allows explicit stops.
- **Branch 1 fires and returns ALLOW**: Not possible — Branch 1 only returns DENY or falls through.
- **Branch 4 with force_explanation=False**: See root cause 3.

Check the last assistant message text from the transcript (Step 3 in the agent) to see which branch fired.

### 6. AskUserQuestion in Last Assistant Message

`matches()` returns `False` when `reader.last_assistant_used_tool("AskUserQuestion")` is True. When Claude uses `AskUserQuestion` as its last tool call and then stops, the handler deliberately allows the stop so the user can answer the question. This is correct behaviour.

---

## Quick Diagnosis Checklist

Run these in order and stop at the first failure:

```bash
# 1. Is daemon running?
/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status

# 2. Does the hook script produce a block response?
echo '{"hook_event_name":"Stop","stop_hook_active":false}' | /workspace/.claude/hooks/stop
# Expected: {"decision":"block","reason":"..."}

# 3. Does the socket return a deny decision?
SOCK=$(ls /workspace/untracked/daemon-*.sock | head -1)
echo '{"event":"Stop","hook_input":{"hook_event_name":"Stop","stop_hook_active":false}}' | nc -U "$SOCK"
# Expected: {"result":{"decision":"deny",...},"handlers_matched":["auto_continue_stop"]}

# 4. Does the internal log show deny entries?
tail -3 /workspace/untracked/stop-events.jsonl
# Expected: {"decision":"deny",...}

# 5. Check transcript outcome
# Find transcript and look for stop_hook_summary entries (see diagnostic commands above)
```

---

## After Fixing: Verify the Fix

After any code change to the stop hook chain:

1. Restart the daemon:

   ```bash
   /workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
   /workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
   ```

2. Run the hook script test:

   ```bash
   echo '{"hook_event_name":"Stop","stop_hook_active":false}' | /workspace/.claude/hooks/stop
   ```

3. Run the unit tests:

   ```bash
   /workspace/untracked/venv/bin/pytest tests/unit/handlers/stop/ -v
   ```

4. Run full QA:

   ```bash
   ./scripts/qa/run_all.sh
   ```

5. In a live Claude Code session, verify that Claude auto-blocks when stopping without `STOPPING BECAUSE:`.

---

## Related Documentation

- `.claude/agents/transcript-inspector.md` — Specialist agent that automates transcript parsing and diagnosis
- `CLAUDE/DEBUGGING_HOOKS.md` — Live hook event debugging with `debug_hooks.sh`
- `CLAUDE/DEBUGGING_TRANSCRIPTS.md` — General transcript debugging guide
- `src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py` — Handler source
- `src/claude_code_hooks_daemon/core/hook_result.py` — `to_json()` routing logic
