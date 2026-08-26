# Plan 00273 — Hook Input Read-Surface Inventory (Task 1.1)

Derived by `scripts/qa/check_input_contract.py --inventory` (AST scan of
`src/claude_code_hooks_daemon/handlers/` event packages plus the shared
helpers in `src/claude_code_hooks_daemon/utils/` and
`src/claude_code_hooks_daemon/handlers/utils/`). StatusLine and the `nitpick`
pseudo-event are excluded by construction (out-of-contract). Regenerate with
the `--inventory` flag rather than editing this table by hand.

## Top-level fields read, per event

| Event / surface   | Fields read                                                                  |
| ----------------- | ---------------------------------------------------------------------------- |
| (shared helpers)  | `permission_mode`, `stopHookActive`\*, `stop_hook_active`, `transcript_path` |
| PermissionRequest | `tool_name`                                                                  |
| PostToolUse       | `cwd`, `session_id`, `tool_input`, `tool_name`, `tool_response`              |
| PreCompact        | `session_id`                                                                 |
| PreToolUse        | `session_id`, `tool_input`, `tool_name`                                      |
| SessionStart      | `hook_event_name`                                                            |
| Stop              | `stop_hook_active`, `transcript_path`                                        |
| UserPromptSubmit  | `prompt`, `session_id`, `transcript_path`                                    |

\* `stopHookActive` is a deliberate legacy camelCase fallback in
`src/claude_code_hooks_daemon/utils/stop_hook_helpers.py`; it appears in no
vendored `input_example` by design and is recorded in
`contracts/claude-code-hooks/INPUT-ALLOWLIST.yaml`.

Every other read is covered by the corresponding event's vendored
`input_example`, so the QA check is green on the current tree.

## Known gap: nested `tool_input` keys (out of scope)

The single most common read is `hook_input.get("tool_input")` (~13 call
sites), whose NESTED keys (`command`, `file_path`, `new_string`, …) are where
much rename risk lives. The vendored examples carry one tool's shape only, so
no substrate exists to check nested keys against; the checker deliberately
records only the top-level `tool_input` read. This is a Non-Goal of Plan
00273 until a per-tool input substrate exists.

## Known gap: project handlers (client repos)

The QA sweep cannot reach client `.claude/project-handlers/`. The checker
primitive (`collect_read_surface` / `check_read_surface`) is importable and
root-parameterised so `bin/hooks-daemon validate-project-handlers` can adopt
it later (precedent: `core/decision_capability.py` sharing). Not done here.

## Task 1.3 — triage of newly documented input fields

| Field                                | Verdict                                                                                                                                         |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `prompt_id` (UserPromptSubmit)       | Recorded gap — no handler needs prompt identity today; consume if a per-prompt dedupe/rate-limit use case appears.                              |
| `agent_id` / `agent_type` (subagent) | Recorded gap — SubagentStop handlers do not branch on agent identity; `HookInputField.AGENT_ID`/`AGENT_TYPE` constants already exist if needed. |
| `last_assistant_message` (Stop)      | Recorded gap — Stop handlers read the transcript file instead (`transcript_path`), which covers more than the last message.                     |
| `permission_suggestions`             | Recorded gap — `auto_approve_reads` decides from `tool_name` + `permission_mode` alone; suggestions add nothing to that policy.                 |
| `effort`                             | Already consumed — by StatusLine handlers, a different (out-of-contract) surface; no hooks-event consumer needed.                               |
