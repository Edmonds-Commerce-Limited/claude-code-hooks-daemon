# Hook Response Schema Drift Audit

> Supporting document for Plan 00271. This report describes THIS repository
> (claude-code-hooks-daemon itself), so it required no generalisation pass
> before being tracked.

**Date**: 2026-08-26. **Audit-only — no files changed.**
**Docs source**: https://code.claude.com/docs/en/hooks.md fetched raw (291,536 bytes) on the audit date; installed Claude Code 2.1.246. All doc claims below were verified against the raw markdown, not a summarised fetch (a first-pass small-model summary contained fabrications, e.g. a `permissionDecision: "escalate"` value that does not exist — a warning in itself about non-verbatim contract capture).
**Daemon side**: `src/claude_code_hooks_daemon/core/response_schemas.py`, `core/hook_result.py`, `core/decision_capability.py`, `constants/events.py`.

## Summary counts

- **Load-bearing drifts: 9** (block a real capability, misroute a refusal/reason, or emit a token the contract ignores)
- **Moderate drifts: 8** (capability gaps nothing currently needs; dead-letter fields)
- **Cosmetic drifts: 4**
- Input-payload validation: the daemon has **no input-schema layer at all** (payloads are consumed ad hoc by handlers), so input drift is structurally invisible rather than mismatched. Noted under DBF.

## The documented contract (as of this fetch)

Universal top-level output fields on every event: `continue` (bool), `stopReason`, `suppressOutput` (documented as a no-op), `systemMessage`, `terminalSequence`. Some events discard some of these; each event section says so.

Decision patterns (docs "Decision control" table):

| Events                                                                                                                              | Pattern                                                                                                                                         |
| ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| UserPromptSubmit, UserPromptExpansion, PostToolUse, PostToolUseFailure, PostToolBatch, Stop, SubagentStop, ConfigChange, PreCompact | top-level `decision: "block"` + `reason`                                                                                                        |
| TeammateIdle, TaskCompleted                                                                                                         | exit 2 or `continue: false`                                                                                                                     |
| TaskCreated                                                                                                                         | exit 2 or `decision: "block"`                                                                                                                   |
| PreToolUse                                                                                                                          | `hookSpecificOutput.permissionDecision`: **allow / deny / ask / defer**, + `permissionDecisionReason`, **`updatedInput`**, `additionalContext`  |
| PermissionRequest                                                                                                                   | `hookSpecificOutput.decision.behavior`: **allow / deny** (no ask), + `updatedInput`, `updatedPermissions`, `message` (deny), `interrupt` (deny) |
| SessionStart                                                                                                                        | `hookSpecificOutput.additionalContext`, `initialUserMessage`, `sessionTitle`, `watchPaths`, `reloadSkills`                                      |
| PostToolUse extras                                                                                                                  | `additionalContext`, `classifierContext` (≥2.1.236), `updatedToolOutput`, `updatedMCPToolOutput`                                                |
| UserPromptSubmit extras                                                                                                             | `decision:"block"`, `reason`, `suppressOriginalPrompt`, `additionalContext`, `sessionTitle`                                                     |
| MessageDisplay                                                                                                                      | `displayContent`                                                                                                                                |
| Elicitation / ElicitationResult                                                                                                     | `action` (accept/decline/cancel), `content`                                                                                                     |
| WorktreeCreate                                                                                                                      | command hook: raw path on stdout, JSON ignored except `terminalSequence`                                                                        |
| WorktreeRemove, Notification, SessionEnd, PostCompact, InstructionsLoaded, StopFailure, CwdChanged, DirectoryAdded, FileChanged     | no decision control; several explicitly **discard `systemMessage`**                                                                             |

Documented event list: 30 events, including `DirectoryAdded`.

## Drift matrix — LOAD-BEARING

1. **PreToolUse: `updatedInput` missing.** `response_schemas.py:26-40` (`additionalProperties: false` on `hookSpecificOutput`) and `hook_result.py:523-545` (formatter has no way to carry it). Documented: replaces the tool's input before execution; also the only way to auto-answer `AskUserQuestion`/`ExitPlanMode` in non-interactive mode (`allow` + `updatedInput`). Blocks Plan 00270's inject/command-rewrite mode outright: if a handler ever emitted it, `_enforce_response_contract` would reject its own response and substitute it away.

2. **PreToolUse: `"defer"` missing from the `permissionDecision` enum.** `response_schemas.py:32` allows only allow/deny/ask; docs add `"defer"` (exit gracefully so the tool can be resumed later). A whole documented decision is inexpressible, and `Decision` (`hook_result.py:18-24`) has no member for it either.

3. **PermissionRequest: daemon emits `decision.behavior: "ask"`, which the contract does not define.** `response_schemas.py:117` (enum includes ask), `hook_result.py:636-637` (emits it), `hook_result.py:76-81` (`REFUSAL_CAPABLE_EVENTS` claims PermissionRequest can carry ASK). Docs define `behavior` as `"allow" | "deny"` only. A project handler returning ASK on PermissionRequest passes every daemon check and is presumably ignored by Claude Code — exactly the silent-drop class `REFUSAL_CAPABLE_EVENTS` exists to prevent, encoded wrongly in the table itself.

4. **PermissionRequest: deny explanation routed into an undocumented field.** `hook_result.py:639-652` deliberately puts the deny reason into `hookSpecificOutput.additionalContext` because "there is nowhere else in this event's schema for an explanation to go" — but the documented field is `decision.message` ("For deny only: tells Claude why the permission was denied"). Docs define no `additionalContext` for this event at all, so the fix for the "refusal arrived bare" bug likely still delivers nothing. `updatedPermissions` and `interrupt` are also inexpressible (`response_schemas.py:105-135`).

5. **UserPromptSubmit: prompt blocking is documented but inexpressible.** Docs: top-level `decision: "block"` + `reason` (+ `suppressOriginalPrompt`). Daemon: `response_schemas.py:183-198` has no top-level fields; `REFUSAL_CAPABLE_EVENTS` (`hook_result.py:66-82`) omits UserPromptSubmit, so a client DENY handler is logged as a dropped refusal and genuinely dropped — yet `constants/events.py:129-136` marks the event `can_block=True`. Three internal sources of truth disagree with each other and with the docs.

6. **SessionStart: "does NOT accept hookSpecificOutput" is no longer true.** `response_schemas.py:139-149` hard-codes `systemMessage`-only on that stated premise. Docs now define `hookSpecificOutput.additionalContext` (context for Claude, injected before the first prompt) plus `initialUserMessage`, `sessionTitle`, `watchPaths`, `reloadSkills`. Consequence: every SessionStart advisory handler's context is emitted as `systemMessage`, which docs describe as a *user-facing warning*, not Claude context. The daemon's session-start advisories may be reaching Claude only via side channels, and the four new capabilities are unreachable. (Live verification of what 2.1.246 does with SessionStart `systemMessage` recommended before fixing.)

7. **PreCompact: documented blocking and a dead-letter output.** Docs put PreCompact in the top-level `decision: "block"` group (a hook can block compaction) and separately say Claude Code *discards* PreCompact `systemMessage`. Daemon: `response_schemas.py:171-177` permits only `systemMessage` — so the one thing the daemon can emit is discarded, and the one documented control is inexpressible. `events.py:138-145` says `can_block=True`; the schema says otherwise.

8. **`DirectoryAdded` is missing from the event catalogue entirely.** Docs list 30 events including it; `constants/events.py` catalogues 30 + StatusLine but has no `DirectoryAdded` entry (grep: zero hits). Per the file's own comment ("A newly discovered Claude Code event is added here; if it cannot be wired... set wired=False AND add its json_key to EXPECTED_UNWIRED"), this is a tracked-gap rule being violated silently — a client cannot attach even a passthrough handler.

9. **Wrong deny token on wired-extra blockable events.** PostToolBatch, PostToolUseFailure, TaskCreated, ConfigChange, UserPromptExpansion, TeammateIdle all have documented blocking (top-level `decision: "block"`, or `continue: false`). The daemon serialises a DENY on any of them through the else-branch `_format_system_message_response` (`hook_result.py:518-521`), which emits `{"decision": "deny", ...}` (`hook_result.py:704-710`) — a token the docs never define (the only top-level decision value is `"block"`). Because these events carry the permissive fail-open schema (`response_schemas.py:285-305`), the invalid token *validates* and goes on the wire, where Claude Code ignores it. A client blocking handler on any of these six events silently fails, with no dropped-refusal log (the `REFUSAL_CAPABLE_EVENTS` check only fires for events *in* the table).

## Drift matrix — MODERATE

- **PostToolUse**: `updatedToolOutput`, `updatedMCPToolOutput`, `classifierContext` inexpressible (`response_schemas.py:49-67`). Output redaction/rewriting and auto-mode classifier annotation are real documented capabilities no handler can use.
- **Universal fields inexpressible on every bespoke-schema event**: `continue`, `stopReason`, `systemMessage`, `terminalSequence` are rejected by `additionalProperties: false` on PreToolUse, PostToolUse, Stop, SubagentStop, PermissionRequest, UserPromptSubmit. `terminalSequence` in particular is documented to work even on events that discard everything else (desktop notifications).
- **UserPromptSubmit**: `sessionTitle` and `suppressOriginalPrompt` missing.
- **Dead-letter `systemMessage`** on events where docs say it is discarded: SessionEnd (`response_schemas.py:157-163`), Notification (206-212), WorktreeCreate/WorktreeRemove (247-266), PreCompact (covered above). The daemon emits into a field the docs say goes nowhere (SessionEnd: "Claude Code discards their JSON output fields, such as `systemMessage`"; Notification: same, except `terminalSequence`). Anything these handlers say may be reaching the debug log only.
- **SubagentStart/Setup context**: docs give both `hookSpecificOutput.additionalContext`; daemon covers them only via the permissive schema, and the systemMessage-formatter path would emit the wrong shape for a context payload.

## Drift matrix — COSMETIC

- **`guidance` is a daemon invention.** Emitted inside `hookSpecificOutput` on PreToolUse, PostToolUse, PermissionRequest, UserPromptSubmit (`hook_result.py:543,567,655,686`) and declared in the bespoke schemas as if contractual. `grep guidance hooks.md` → zero output-field hits. Claude Code ignores an unknown key, so this is harmless on the wire, but the schemas present it as part of the contract.
- **`suppressOutput`**: docs now document it as accepted-but-no-op; daemon never emits it. No action.
- **Stop `decision: "block"` without `reason`**: docs say `reason` is "Required when decision is block"; the daemon can emit a bare block (`hook_result.py:604-607`).
- **StatusLine**: not a hooks event in the docs at all (statusline is a separate feature with its own contract) — the daemon's bespoke handling is correct, just worth a comment noting it is out-of-contract by design.

## Input-payload drift surface

The daemon validates responses only; there is no input schema. Handlers read fields ad hoc (`stop_hook_active`, `tool_input`, etc. — all still documented). New documented input fields the daemon does not model anywhere: `prompt_id` (≥2.1.196), `effort` (`{level}`), `agent_id`/`agent_type` on subagent-context calls, `last_assistant_message` on Stop/SubagentStop, `permission_suggestions` on PermissionRequest. None is a break (extra input fields are simply unread), but the absence of any input contract means an input rename would surface only as handlers silently never matching. The DBF guard below should vendor input examples per event too.

## DBF: the missing guard

The defect class is "the vendored idea of the contract lives implicitly in `response_schemas.py` and rots invisibly". Options evaluated:

**(a) Vendored contract + QA diff — RECOMMENDED.** Add `contracts/claude-code-hooks/` (tracked): one JSON file per event capturing the documented output fields, allowed decision tokens/enums, and an input example, plus a `META.json` recording the docs URL, fetch date, and the Claude Code version last audited against. A documented refresh procedure (a script that curls `hooks.md` to a scratch file and a human/agent updates the JSON from it — the extraction step must not be automated-and-trusted, per the fabricated-summary incident above). A QA check (network-free) then asserts, per event: every field in the daemon's bespoke schema exists in the vendored contract (catches inventions like `guidance` becoming load-bearing), every vendored decision token the daemon claims to deliver (`REFUSAL_CAPABLE_EVENTS`, `can_block`) is actually documented, and every vendored event name exists in `constants/events.py` (would have caught `DirectoryAdded`). It deliberately does NOT require the daemon to express every documented field — capability gaps are reported as advisories with a per-field allowlist carrying a reason, so "known, deliberately unsupported" is recorded rather than silent.

**(b) Version-staleness advisory — adopt as a cheap companion.** A `last_audited_claude_code_version` constant next to `META.json`; the existing SessionStart machinery (sibling of `version_check`) advises when the installed Claude Code version exceeds it: "hooks contract last audited against 2.1.246 — re-run the refresh procedure". This is what makes (a) get refreshed at all; without it the vendored copy rots exactly like the schemas did.

**(c) `debug_hooks.sh` live capture — evidence, not a guard.** It observes only shapes actually exercised in a session, and can never observe a field the daemon fails to *emit* (the whole load-bearing class here is emit-side). Keep it as the verification step for individual fixes (e.g. confirming what 2.1.246 does with SessionStart `systemMessage`), not as the sync mechanism.

**Recommendation: (a) + (b).** (a) is the only option that turns both drift directions into a mechanically checkable diff without network in tests; (b) is the trigger that keeps (a) current.

## Suggested fix order (for the eventual plan)

1. `REFUSAL_CAPABLE_EVENTS` / `can_block` / schema three-way reconciliation (items 3, 5, 7, 9) — these are wrong *claims*, cheapest to fix, and they gate what project handlers are told is possible.
2. PreToolUse `updatedInput` + `defer` (unblocks Plan 00270).
3. PermissionRequest `message`/`updatedPermissions`/`interrupt` and re-route the deny reason.
4. SessionStart `hookSpecificOutput` migration (verify live first).
5. Add `DirectoryAdded`; PostToolUse rewrite fields; universal fields where useful (`terminalSequence`).
6. Land the DBF guard before or with 1 so the fixes are pinned to a vendored contract.
