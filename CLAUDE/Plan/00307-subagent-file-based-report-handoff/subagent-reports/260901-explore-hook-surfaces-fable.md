# Task 1.2 — hook-surface verification (Explore agent report)

First report filed under the Task 2.2 convention (`subagent-reports/`,
`{yymmdd}-{agent-name}-{model}.md`).

## 1. SubagentStop contract (`contracts/claude-code-hooks/SubagentStop.json`)

- Inputs: `session_id`, `transcript_path` (the PARENT session jsonl), `cwd`,
  `permission_mode`, `hook_event_name`, `stop_hook_active`, `agent_id`,
  `agent_type` (e.g. "Explore"), `agent_transcript_path`
  (`.../<session>/subagents/agent-<id>.jsonl`), `last_assistant_message`,
  `background_tasks`, `session_crons`.
- Output: `can_block: true`, `block_mechanism: "top-level-decision"`,
  `top_level_decision_enum: ["block"]`, plus
  `continue/stopReason/suppressOutput/systemMessage/terminalSequence/reason`
  and `hookSpecificOutput.additionalContext`. "Same decision control as
  Stop; reason required when decision is 'block'." Contract audited against
  Claude Code 2.1.252.
- **Key for Phase 3: `last_assistant_message` gives the subagent's final
  report text directly — no transcript parse needed to size-check it.**

## 2. Wiring

- SubagentStop is fully wired: `constants/events.py:243-252`
  (`SUBAGENT_STOP`, `can_block=True`, `category="subagent"`,
  `requires_client_translation=True`). Response schema
  `core/response_schemas.py:105,410`; input schema
  `core/input_schemas.py:222-232`; formatting
  `core/hook_result.py:438,577,669`. Handler base alias
  `handler_bases.py:133` (`SubagentStopHandlerBase = BlockingHandler`).
- **Zero handlers ship today** — `handlers/subagent_stop/__init__.py` is an
  intentionally empty package (emptied in Plan 00237): the drop-in home for
  the Phase 3 blocker.
- Caveat: the daemon input schema declares `subagent_id`/`subagent_type`
  but the vendored contract says `agent_id`/`agent_type`/
  `agent_transcript_path`/`last_assistant_message`. `additionalProperties: True` lets the real fields through unvalidated — the stale schema should
  be updated in Phase 3.

## 3. Transcript machinery

- `utils/stop_hook_helpers.py:59-88` `get_transcript_reader(hook_input)`
  wraps `TranscriptReader.load_tail(path)` (`core/transcript_reader.py`,
  bounded tail read, Plan 00177); also `is_stop_hook_active()` (line 42).
- It reads `hook_input[transcript_path]` hardcoded; for a subagent
  transcript call `TranscriptReader().load_tail(hook_input["agent_transcript_path"])`
  directly (same JSONL format, reader is path-agnostic) or add a small
  variant taking an explicit path.

## 4. PreToolUse on Agent/Task

- PreToolUse input carries `tool_name`, `tool_input`, `tool_use_id`,
  `prompt_id`; outputs `permissionDecision` (allow/deny/ask/defer),
  `permissionDecisionReason`, `updatedInput` (replaces the ENTIRE input
  object), `additionalContext`.
- Working precedent: `handlers/pre_tool_use/agent_isolation_advisor.py:95-104`
  keys on `ToolName.TASK` ("Task", `constants/tools.py:57`) and reads
  `tool_input["prompt"]`.
- **Phase 2 injection is feasible via `updatedInput`** — but it replaces
  the whole input object, so the handler must echo back every `tool_input`
  field with only `prompt` amended. `additionalContext` serves the
  advisory-only mode.

## 5. SendMessage

- **No hook surface.** No contract event covers inter-agent messaging (33
  events; closest are SubagentStart/SubagentStop/TaskCreated/TaskCompleted/
  MessageDisplay/TeammateIdle), and `ToolName` has no SEND_MESSAGE member.
  SendMessage-based handoff enforcement is not implementable today; scope
  Phase 3 to the Agent-return channel and note the gap.

## Feasibility flags

- Phase 2: feasible (model on agent_isolation_advisor; updatedInput
  full-object rewrite for strict mode).
- Phase 3: feasible via `last_assistant_message` + `decision: "block"`
  (reason required). Handle: (a) `requires_client_translation=True` — the
  relay transport has no block equivalent (Plan 00290), so a block may not
  work over the relay; (b) guard on `stop_hook_active` to avoid re-entry
  loops.
- `mode_interceptor.py:41,65` deliberately does not intercept SubagentStop,
  so unattended mode will not interfere.
