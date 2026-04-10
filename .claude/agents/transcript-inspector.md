---

## name: transcript-inspector description: Specialist agent for diagnosing stop hook failures by reading Claude Code session transcripts. Use when the stop hook is not blocking as expected, Claude keeps stopping without required explanation, or preventedContinuation is false when it should be true. tools: Read, Bash, Glob, Grep model: sonnet

# Transcript Inspector - Stop Hook Dogfooding Diagnostics

## Purpose

Diagnose stop hook failures by reading Claude Code session transcripts and cross-referencing with daemon logs. Primary use case: "Claude stopped when it should have been blocked" or "the stop hook isn't working."

## How to Use This Agent

Invoke when:

- Claude stops without a `STOPPING BECAUSE:` prefix and the daemon did not block it
- A user had to type "go" or "continue" manually (symptom of broken stop hook)
- `preventedContinuation: false` appears in transcript when it should be `true`
- Any stop hook dogfooding regression

## Step 1: Find the Current Transcript

```bash
# List all transcript files for this project, sorted by modification time (newest last)
ls -lt /root/.claude/projects/-workspace/*.jsonl 2>/dev/null | head -5

# The most recent file is the current session
TRANSCRIPT=$(ls -t /root/.claude/projects/-workspace/*.jsonl 2>/dev/null | head -1)
echo "Transcript: $TRANSCRIPT"
```

The project path encoding: `/workspace` → `-workspace`. If running from a different path, adjust accordingly.

## Step 2: Locate stop_hook_summary Entries

These are the definitive outcome records for every stop hook invocation.

```python
#!/usr/bin/env python3
import json
import sys

transcript = sys.argv[1]  # pass transcript path as arg

with open(transcript) as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}\n")

for i, line in enumerate(lines):
    try:
        e = json.loads(line)
    except json.JSONDecodeError:
        continue

    # Stop hook outcome record
    if e.get('subtype') == 'stop_hook_summary':
        print(f"Line {i}: stop_hook_summary")
        print(f"  preventedContinuation : {e.get('preventedContinuation')}")
        print(f"  level                 : {e.get('level')}")
        print(f"  hasOutput             : {e.get('hasOutput')}")
        print(f"  hookErrors            : {e.get('hookErrors')}")
        print(f"  raw                   : {json.dumps(e, indent=2)}")
        print()

    # Stop hook progress event (hook firing)
    if (e.get('type') == 'progress'
            and isinstance(e.get('data'), dict)
            and e['data'].get('type') == 'hook_progress'
            and e['data'].get('hookEvent') == 'Stop'):
        print(f"Line {i}: Stop hook FIRING (progress event)")
        print(f"  hookName : {e['data'].get('hookName')}")
        print(f"  toolUseID: {e.get('toolUseID')}")
        print()
```

Run it:

```bash
python3 /tmp/find_stop_hooks.py "$TRANSCRIPT"
```

### Interpreting stop_hook_summary Fields

| Field                   | Broken value   | Working value          | Meaning                                    |
| ----------------------- | -------------- | ---------------------- | ------------------------------------------ |
| `preventedContinuation` | `false`        | `true`                 | Hook did NOT block (broken) vs DID block   |
| `level`                 | `"suggestion"` | `"error"` or `"block"` | Suggestion = daemon returned `{}` or ALLOW |
| `hasOutput`             | `false`        | `true`                 | Hook script produced no output at all      |
| `hookErrors`            | non-empty      | `[]`                   | Hook script errored                        |

**The symptom**: `preventedContinuation: false` + `level: "suggestion"` = daemon returned `{}` (ALLOW) when it should have returned `{"decision":"block","reason":"..."}`.

## Step 3: Find the Last Assistant Message Before Stop

```python
#!/usr/bin/env python3
import json, sys

transcript = sys.argv[1]

with open(transcript) as f:
    lines = f.readlines()

# Find the last assistant message before each stop_hook_summary
stop_indices = []
for i, line in enumerate(lines):
    try:
        e = json.loads(line)
        if e.get('subtype') == 'stop_hook_summary':
            stop_indices.append(i)
    except json.JSONDecodeError:
        continue

if not stop_indices:
    print("No stop_hook_summary entries found")
    sys.exit(0)

for stop_idx in stop_indices:
    print(f"\n--- Stop event at line {stop_idx} ---")
    # Walk backwards to find last assistant message
    for i in range(stop_idx - 1, max(stop_idx - 50, 0), -1):
        try:
            e = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if e.get('type') == 'assistant':
            msg = e.get('message', {})
            content = msg.get('content', [])
            texts = []
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get('type') == 'text':
                    texts.append(block.get('text', ''))
            last_text = ' '.join(texts)
            print(f"Last assistant text (line {i}):")
            print(f"  {last_text[:300]!r}")
            break
```

```bash
python3 /tmp/find_last_assistant.py "$TRANSCRIPT"
```

**What to look for**: Does the assistant text start with `STOPPING BECAUSE:`? If yes, the handler should have returned ALLOW. If no, it should have blocked with DENY.

## Step 4: Test the Hook Script Directly

This isolates whether the shell script layer is broken.

```bash
# Test the stop hook script with a minimal input
echo '{"hook_event_name":"Stop","stop_hook_active":false}' | /workspace/.claude/hooks/stop
```

**Expected output when working (handler blocks):**

```json
{"decision":"block","reason":"You stopped without explaining why..."}
```

**Broken outputs:**

```json
{}
```

Empty object = daemon returned ALLOW. The hook script is fine but the daemon returned the wrong decision.

```
(no output)
```

Completely silent = hook script crashed or daemon is down.

```
{"error":"..."}
```

Explicit error = daemon startup failed or socket error.

## Step 5: Test the Daemon Socket Directly

This isolates whether the handler logic itself is broken.

```bash
# Find the daemon socket
SOCK=$(ls /workspace/untracked/daemon-*.sock 2>/dev/null | head -1)
echo "Socket: $SOCK"

# Send a Stop event directly to the daemon
echo '{"event":"Stop","hook_input":{"hook_event_name":"Stop","stop_hook_active":false}}' \
    | nc -U "$SOCK"
```

**Expected when working:**

```json
{"result":{"decision":"deny","reason":"You stopped without explaining why..."},"timing_ms":1.23,"handlers_matched":["auto_continue_stop"]}
```

**Broken - ALLOW with no reason:**

```json
{"result":{"decision":"allow","reason":null,"context":[]},"timing_ms":0.41,"handlers_matched":[]}
```

This means no handler matched. Check `handlers_matched: []` — if empty, the handler's `matches()` returned False.

**Broken - empty:**

```json
{}
```

The socket returned `{}`. This is the to_json() ALLOW path — decision is ALLOW with no context.

## Step 6: Cross-Reference with the Daemon's Internal Log

The `auto_continue_stop` handler writes its own JSONL log:

```bash
cat /workspace/untracked/stop-events.jsonl 2>/dev/null | tail -10
```

Each line is:

```json
{"timestamp":"2026-03-30T...","decision":"deny","reason_prefix":"You stopped without...","stop_hook_active":false}
```

If the log shows `"decision":"deny"` but the transcript shows `preventedContinuation: false`, the daemon is blocking correctly but the response is not reaching Claude Code. Check the hook script → socket pipe.

If the log is empty or missing entries that match the transcript's stop events, the handler never ran (matches() returned False, or daemon was down).

## Step 7: Check the hook_input the Handler Received

The `stop_hook_active` field prevents infinite loops. If it is `true` in the input, the handler exits early.

```bash
# Check what hook_input the stop script is actually sending
echo '{"hook_event_name":"Stop","stop_hook_active":false}' \
    | jq -c '{event: "Stop", hook_input: .}'
# Should produce: {"event":"Stop","hook_input":{"hook_event_name":"Stop","stop_hook_active":false}}
```

If `stop_hook_active` is `true`, the handler deliberately allows (re-entry guard). This is correct behaviour, not a bug.

## Step 8: Check transcript_path in hook_input

The `auto_continue_stop` handler reads the transcript to inspect the last assistant message. If `transcript_path` is missing or wrong, the `get_transcript_reader()` returns None and the handler falls through to Branch 4 (force_explanation), which should still DENY.

```bash
# Simulate full hook_input with transcript_path
echo "{\"hook_event_name\":\"Stop\",\"stop_hook_active\":false,\"transcript_path\":\"$TRANSCRIPT\"}" \
    | /workspace/.claude/hooks/stop
```

## Diagnostic Decision Tree

```
Claude stopped without STOPPING BECAUSE: prefix
└── Check stop_hook_summary in transcript
    ├── preventedContinuation: true → Hook DID block. Claude ignored it. (Claude Code bug, not daemon)
    └── preventedContinuation: false
        ├── hasOutput: false → Hook script produced nothing
        │   ├── Check daemon is running: $PYTHON -m claude_code_hooks_daemon.daemon.cli status
        │   └── Check hook script: echo '...' | /workspace/.claude/hooks/stop
        └── hasOutput: true, level: "suggestion"
            ├── Daemon returned {} (ALLOW)
            ├── Test socket directly (Step 5)
            │   ├── handlers_matched: [] → matches() returned False
            │   │   ├── stop_hook_active was true in hook_input → re-entry guard (correct)
            │   │   └── bug in matches() logic
            │   └── handlers_matched: ["auto_continue_stop"] → handle() returned ALLOW
            │       ├── force_explanation=False in config → intended behaviour
            │       └── _has_stop_explanation() returned True → STOPPING BECAUSE: prefix present
            └── Check stop-events.jsonl (Step 6)
                ├── Entry present with decision:deny → response not reaching Claude Code
                └── No entry → handler never ran (daemon down, or matches() issue)
```

## Common Root Causes

### 1. `stop_hook_active: true` in hook_input (not a bug)

The handler intentionally allows when it detects it is being called from within a stop hook response cycle. Claude Code sets `stop_hook_active: true` when executing the auto-continue instruction. This is correct.

### 2. `force_explanation: false` in config

If `.claude/hooks-daemon.yaml` has `auto_continue_stop.options.force_explanation: false`, Branch 4 will ALLOW instead of DENY. Check config.

### 3. Daemon not running

```bash
/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
# If not RUNNING:
/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

### 4. `to_json()` routing bug

`HookResult.to_json(event_name)` routes on the exact string `"Stop"`. If the FrontController is called with a different event_name string (e.g. `"stop"` lowercase), `_format_stop_response()` is never called and the response falls through to systemMessage format, which does not include a `decision` field. Test: send to socket and verify `decision: deny` appears at top level.

### 5. transcript_path missing → handler still blocks

Even without a transcript, Branch 4 (`force_explanation=True`) will DENY. If the handler is not blocking, transcript_path is not the cause.

## Key Entry Types in Transcript

| type        | subtype/data.type                  | Meaning                                                |
| ----------- | ---------------------------------- | ------------------------------------------------------ |
| `progress`  | `hook_progress`, `hookEvent: Stop` | Stop hook is firing                                    |
| `system`    | `stop_hook_summary`                | Stop hook outcome (check `preventedContinuation`)      |
| `assistant` | —                                  | Last Claude message before stop                        |
| `user`      | — with `content: "go"`             | User had to resume manually (broken stop hook symptom) |

## Quick Reference Commands

```bash
# 1. Find transcript
TRANSCRIPT=$(ls -t /root/.claude/projects/-workspace/*.jsonl | head -1)

# 2. Show all stop outcomes
python3 -c "
import json
for i,l in enumerate(open('$TRANSCRIPT')):
    e=json.loads(l.strip()) if l.strip() else {}
    if e.get('subtype')=='stop_hook_summary':
        print(i, e.get('preventedContinuation'), e.get('level'), e.get('hasOutput'))
"

# 3. Test hook script
echo '{"hook_event_name":"Stop","stop_hook_active":false}' | /workspace/.claude/hooks/stop

# 4. Test daemon socket
SOCK=$(ls /workspace/untracked/daemon-*.sock | head -1)
echo '{"event":"Stop","hook_input":{"hook_event_name":"Stop","stop_hook_active":false}}' | nc -U "$SOCK"

# 5. Check internal log
tail -5 /workspace/untracked/stop-events.jsonl

# 6. Daemon status
/workspace/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
```
