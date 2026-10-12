# N442 (GitHub #95): hooks contract refresh, audit record

## Verdict

Before: `contract-status` CHANGED (recorded 266649 bytes, sha256 3a1f9445..., upstream 268811 bytes, sha256
31754d5adce5052af35acf85dc2ed207bb082b7dbf87f25218047b10a024a073). After: exit 0, `unchanged`. Raw body saved
(untracked) at `untracked/hooks-raw.md` in the worktree, fetched by the CLI's plain https GET; no summarising fetch.
`claude --version` = 2.1.296, so `last_audited_claude_code_version` is unchanged. Still 33 events; the
documented event table and the 33 `<Event>.json` files are the same set (checked by comparison).

## Baseline

No exact copy of the 266649-byte body exists on disk. Baseline was built as: (1) the vendored
`remote-docs/code.claude.com/docs/en/hooks.md` body (fetched 2026-10-08, 250549 bytes after frontmatter), diffed
against the new raw (673 diff lines); (2) the batch N report (`261011-batch-n-sonnet.md`), which lists what the
2.1.296 audit recorded; (3) each hunk checked against the current per-event JSONs. A hunk counts as already audited
when the JSON or the batch N report reflects it. Already audited (not re-recorded): `onFailure` (v2.1.295), `mcp_server`,
`agent_id` on TaskCreated/TaskCompleted/TeammateIdle (v2.1.290 rows), Elicitation top-level `decision` and "Other
ways to decline an elicitation", `session_title`, exit-code outcome rewrite (not in the contract JSON), uuid-only
example churn. Limit: a change that landed between the vendored copy and the 266649 body but that N375 missed
cannot be told apart from new; those would show here as "new" and were audited anyway.

## Changed claims (each with the supporting raw sentence)

| File                                                              | Change                                                                                                                                                                                                                                                                       | Raw support                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PreToolUse, PostToolUse, Stop `conditional_input_fields.agent_id` | The "Present ONLY when ... subagent call / to distinguish subagent hook calls from main-thread calls" wording is gone upstream (no `main-thread` anywhere in the raw). Reworded to the new text and flagged that the absence on a main thread now rests on the examples only | "`agent_id` \| Unique identifier for the subagent or in-process teammate the hook fires in."; "When a subagent calls a tool, tool events such as `PreToolUse` and `PostToolUse` fire the same configured hooks as in the main conversation, and the input carries the `agent_id` and `agent_type` [common input fields](#common-input-fields) that identify the subagent."                                                  |
| ElicitationResult `input_example`                                 | `elicitation_id` removed                                                                                                                                                                                                                                                     | The raw ElicitationResult example ends `"content": { "username": "alice" }, "mode": "form"`; the field list still says "optional `mode`, `elicitation_id`, and `content` fields."                                                                                                                                                                                                                                           |
| Elicitation notes                                                 | exit 2 now declines with no dialog; stderr/reason not shown; accept skips dialog; decline from one hook overrides others; stale `elicitation_id` sentence corrected                                                                                                          | "Declines the request, and no dialog appears" (exit-code-2 table); "Neither the user nor the server sees why your hook declined, because Claude Code doesn't show your stderr or your `reason`."; "For a URL-mode request, a hook that returns `accept` skips the dialog, so the URL never opens."; "When several hooks match the same request, a decline from one of them overrides an `accept` or `cancel` from another." |
| ElicitationResult notes                                           | pass-through/change/block/cancel outcomes; whole-content replacement; `action` required; Elicitation answer skips ElicitationResult hooks                                                                                                                                    | "Your `content` replaces the user's whole `content` object"; "Claude Code ignores a `hookSpecificOutput` that has no `action`."; "When an [Elicitation](#elicitation) hook answers a request, Claude Code sends that answer to the server without running ElicitationResult hooks."                                                                                                                                         |
| PreToolUse notes                                                  | `allow` exception for network-path reads; WebFetch `offset`                                                                                                                                                                                                                  | "`\"allow\"` skips the permission prompt, except for the [actions no mode auto-approves](...), for [reads from network paths](/docs/en/permissions#network-paths), and for `AskUserQuestion` and `ExitPlanMode`"; "`offset` \| number \| `100000` \| Optional number of characters to skip from the start of the page. ... Requires Claude Code v2.1.290 or later"                                                          |
| SessionStart notes                                                | plugin finishing install late; PowerShell and `CLAUDE_ENV_FILE`                                                                                                                                                                                                              | "Claude Code ignores both fields from a plugin that finishes installing after the SessionStart hooks have run."; "`CLAUDE_ENV_FILE` ... neither does a hook that runs in PowerShell"; "PowerShell commands receive the variables from `CLAUDE_ENV_FILE` too, in Claude Code v2.1.296 or later"                                                                                                                              |
| PreModelSwitch notes                                              | other exit codes are a non-blocking error (was "shows its stderr and applies the switch")                                                                                                                                                                                    | "A hook that exits with a code other than 0 or 2 and prints no JSON decision is a non-blocking error, as described under [Other exit codes](#other-exit-codes)."                                                                                                                                                                                                                                                            |
| WorktreeCreate notes                                              | trigger list; bare `git worktree add` through Bash does not fire it                                                                                                                                                                                                          | "When Claude runs `git worktree add` through the Bash tool rather than calling `EnterWorktree`, your WorktreeCreate hook doesn't run." plus the six-bullet trigger list                                                                                                                                                                                                                                                     |
| WorktreeRemove notes                                              | extra triggers; subagent/workflow-agent worktrees are kept                                                                                                                                                                                                                   | "When a subagent or a workflow agent finishes, Claude Code keeps the worktree your WorktreeCreate hook made for it and doesn't run your WorktreeRemove hook." plus the `ExitWorktree` and `claude remote-control` bullets                                                                                                                                                                                                   |
| META.json                                                         | fetch_date 2026-10-12, docs_bytes 268811, docs_sha256 as above                                                                                                                                                                                                               | `contract-status` output                                                                                                                                                                                                                                                                                                                                                                                                    |

Pinned test moved: `tests/unit/qa/test_check_hook_contract.py` (`AUDITED_SHA256`, `AUDITED_BYTES`). The version pin in
`tests/unit/handlers/session_start/test_contract_staleness.py` stays 2.1.296 (grep of `tests/` for 2.1.296 done; the
version is unchanged). No other file pins the sha or byte count.

## Recorded, not in the contract JSON

`onFailure` is now documented as a hook config field; a failed hook can block; exit-code outcome table rewritten
(JSON parse failure or schema failure is a non-blocking error on every code but 2; exit 2 still blocks); the async
response may now span lines (v2.1.295); `Hooks:` debug-log duration lines (v2.1.296); `<system-reminder>` tags in
`additionalContext` are escaped to `&lt;`; WebFetch `offset`; TaskCreated block wording. All shown as unchanged
behaviour for the daemon except as listed under findings.

## QA

- `llm_qa.py hook_contract`: 0 violations, 32 allowlisted gaps (unchanged count); no stale allowlist entry.
- `llm_qa.py input_contract`: 0 violations, 5 allowlisted gaps.
- `pytest tests/unit/qa/test_check_hook_contract.py tests/unit/handlers/session_start/test_contract_staleness.py`: 78 passed.
- Vendored copy refreshed with `remote-docs refresh --path remote-docs/code.claude.com/docs/en/hooks.md` (updated, recorded fidelity kept); `.claude/REMOTE-DOCS.md` index moved with it.

## Findings for the coordinator (none acted on)

1. `agent_id` now also identifies in-process teammates, and upstream no longer states it is absent on a main-thread call.
   Daemon code that treats a present `agent_id` as "inside a subagent" (e.g. `subagent_cron_delete_blocker`,
   `subagent_full_qa_blocker`, `subagent_worktree_write_guard`, `subagent_report_*`, `cron_subagent_stop_enforcer`)
   may now fire for a teammate. Needs a decision; not changed.
2. `additionalContext` containing `<system-reminder>` or `</system-reminder>` is delivered with `<` escaped to `&lt;`.
   Any handler injecting such tags inside `additionalContext` will have them neutralised. Not checked per handler.
3. PreModelSwitch exit-other-than-0/2 is now a non-blocking error rather than "stderr shown, switch applied"; no
   daemon behaviour depends on it.
4. No `ALLOWLIST.yaml` / `INPUT-ALLOWLIST.yaml` entry was added or needed.
