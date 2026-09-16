# Evidence: `agent_id` distinguishes a subagent `PreToolUse` from a main-thread one

Captured from the live daemon's DEBUG log on 2026-09-15, in the main `/workspace`
checkout. **Two real payloads, same daemon, same session, 45 milliseconds
apart.** Neither is synthetic.

Session and prompt IDs are redacted to all-same-digit placeholders per this
project's standing rule — all-zero for `session_id`, all-one for `prompt_id`, the
same placeholder in both payloads because their being IDENTICAL is part of the
finding. Nothing else is altered.

This settles Plan 00418 Task 1.1, which is a STOP GATE. It matters that these are
captured rather than cited: the first attempt at this handler died because the
project reasoned about this exact field from documentation, and ledger 00413 N12
found the contract could not have shown it either — `agent_id` is CONDITIONAL, so
every `input_example` depicts a main-thread call where it is correctly absent.

## A — subagent call (a dispatched teammate's `Read`)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/root/.claude/projects/-workspace/00000000-0000-0000-0000-000000000000.jsonl",
  "message": null,
  "prompt": null,
  "cwd": "/workspace",
  "prompt_id": "11111111-1111-1111-1111-111111111111",
  "permission_mode": "bypassPermissions",
  "agent_id": "acron-teeth-27051c266e79714e",
  "agent_type": "cron-teeth",
  "effort": { "level": "high" },
  "hook_event_name": "PreToolUse",
  "tool_use_id": "toolu_01AGBbrTqomjSGzkoWimo8Gi"
}
```

## B — main-thread call (`Bash`, issued directly in the main turn)

```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "echo PREMISECHECK7731 && bin/hooks-daemon logs …",
    "description": "Dump debug log containing this command's own payload"
  },
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/root/.claude/projects/-workspace/00000000-0000-0000-0000-000000000000.jsonl",
  "message": null,
  "prompt": null,
  "cwd": "/workspace",
  "prompt_id": "11111111-1111-1111-1111-111111111111",
  "permission_mode": "bypassPermissions",
  "effort": { "level": "high" },
  "hook_event_name": "PreToolUse",
  "tool_use_id": "toolu_01Ht2bXDZ9eZkUvE8sxQGPNQ"
}
```

## What this establishes

1. **`agent_id` is present on a subagent call and absent on a main-thread one.**
   Gating enforcement on its ABSENCE is sound. This is exactly the distinction
   the original handler needed and could not get.

2. **`agent_type` behaves the same way HERE, but is not equivalent.** It is
   absent from B and present in A, yet the vendored contract records that
   `agent_type` is also delivered when a session is launched with
   `claude --agent <name>` — in which case it would appear on a MAIN-THREAD call
   too. So `agent_type` is **not** a safe discriminator and `agent_id` is. A
   handler gating on `agent_type` would pass against this capture and silently
   mis-fire for anyone launching with `--agent`: correct in testing, wrong for a
   subset of users.

3. **`session_id` is IDENTICAL in A and B.** A dispatched teammate runs in the
   same session, so `session_id` carries no information about which agent fired
   the event. Anything reaching for it as a discriminator is wrong.

4. **`prompt_id` is also identical**, and is likewise not a discriminator.

## How it was captured, and why not `debug_hooks.sh`

`scripts/debug_hooks.sh` is the documented tool and would normally be right. It
was NOT used because it rewrites `.claude/hooks-daemon.yaml` and restarts the
daemon, and five QA suites were running in worktrees at the time — an avoidable
disturbance.

Instead: the daemon logs a `PreToolUse` payload BEFORE the command runs, so a
single command carrying a unique marker that then dumps the DEBUG log captures
its own payload with no race at all. Two earlier attempts to catch a marker by
messaging between processes both lost to the ~1000-entry ring buffer; this
technique cannot lose, because the write precedes the read within one command.
Worth keeping as a general trick for capturing a main-thread payload cheaply.
