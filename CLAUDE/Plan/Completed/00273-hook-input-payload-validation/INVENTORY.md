# Plan 00273 — Hook Input Read-Surface Inventory (Task 1.1)

Derived by `scripts/qa/check_input_contract.py --inventory` (AST scan of
`src/claude_code_hooks_daemon/handlers/` event packages plus the SHARED
surface: `src/claude_code_hooks_daemon/utils/`,
`src/claude_code_hooks_daemon/core/` (front controller, mode interceptor,
session state, core utils) and `src/claude_code_hooks_daemon/handlers/utils/`).
StatusLine and the `nitpick` pseudo-event are excluded by construction
(out-of-contract) as event packages; StatusLine-payload fields read by shared
core code still surface on the shared row and are allowlisted. Regenerate
with the `--inventory` flag rather than editing this table by hand.

## Top-level fields read, per event

| Event / surface   | Fields read                                                                                                                                                       |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| (shared)          | `context_window`\*, `cwd`, `model`, `permission_mode`, `stopHookActive`\*, `stop_hook_active`, `terminal_columns`\*, `tool_input`, `tool_name`, `transcript_path` |
| PermissionRequest | `tool_name`                                                                                                                                                       |
| PostToolUse       | `cwd`, `session_id`, `tool_input`, `tool_name`, `tool_response`                                                                                                   |
| PreCompact        | `session_id`                                                                                                                                                      |
| PreToolUse        | `session_id`, `tool_input`, `tool_name`                                                                                                                           |
| SessionStart      | `hook_event_name`                                                                                                                                                 |
| Stop              | `stop_hook_active`, `transcript_path`                                                                                                                             |
| UserPromptSubmit  | `prompt`, `session_id`, `transcript_path`                                                                                                                         |

\* Allowlisted in `contracts/claude-code-hooks/INPUT-ALLOWLIST.yaml`:
`stopHookActive` is a deliberate legacy camelCase fallback in
`src/claude_code_hooks_daemon/utils/stop_hook_helpers.py`;
`terminal_columns` (core/front_controller.py) and `context_window`
(core/session_state.py) are StatusLine-payload fields — StatusLine is
out-of-contract by design, so no vendored `input_example` can document them.

Every other read is covered by the corresponding event's vendored
`input_example`, so the QA check is green on the current tree.

## Known gap: nested `tool_input` keys (out of scope)

The single most common read is `hook_input.get("tool_input")` (~13 call
sites), whose NESTED keys (`command`, `file_path`, `new_string`, …) are where
much rename risk lives. The vendored examples carry one tool's shape only, so
no substrate exists to check nested keys against; the checker deliberately
records only the top-level `tool_input` read. This is a Non-Goal of Plan
00273 until a per-tool input substrate exists.

## Known gap: AST scan shape limits

The scan detects `hook_input.get(<literal-or-HookInputField>)` and
`hook_input[<literal-or-HookInputField>]` only. Reads it CANNOT see:

- an aliased dict (`data = hook_input; data.get("x")`) or a renamed
  parameter (`def handle(self, payload: dict)`)
- membership tests (`"x" in hook_input`) and `.keys()`/iteration
- a key held in a local variable or computed at runtime
- attribute-style access on a wrapper object

A read arriving by any of those shapes is silently absent from the inventory
and never checked. The convention across `src/` is the literal/`HookInputField`
shape on a parameter named `hook_input`, so residue today is nil, but the
limit is structural — a future refactor into one of these shapes would
silently shrink the checked surface.

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
