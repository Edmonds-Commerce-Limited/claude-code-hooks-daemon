# Batch N (group K): N374 residuals, N375, N333, N335

## N375 - fixed

Re-fetched `https://code.claude.com/docs/en/hooks.md` raw (266649 bytes, sha256
`3a1f944503d05a61fdc0fac62add9ba3d877ccb03dd4ef9c3c79881c973938ef`; the prior audit held 322902).
Correction after review round 1: this section first said the previous raw text was not kept and that
field names matched. Both were wrong. A copy from 2026-09-16 exists at
`/workspace/untracked/scratch/hooks-raw.md` in the main checkout and was diffed against the new text;
the first pass checked output fields and a heuristic of input-table rows and so missed the
`mcp_server` object. Each of the 33 per-event JSON files was also checked by script against the new
doc's event section (output fields, enums, decision enum, decision-control table rows, input tables).

Findings:

- All 33 events still documented; output-side field names and enums match, except:
- Input side, added in round 2: `mcp_server {name, source}` (v2.1.274) on PreToolUse,
  PermissionRequest, PostToolUseFailure, PermissionDenied (daemon reads it nowhere: N412);
  `agent_id` (v2.1.290) on TaskCreated, TaskCompleted, TeammateIdle.
- Newly documented, recorded only: `onFailure` hook config (v2.1.295); Stop hook 8-continuation cap
  and `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` (ledger N411); Elicitation(Result) ignored a top-level
  `decision` from v2.1.105 to v2.1.284.
- `Elicitation` and `ElicitationResult`: the doc (decision table and "Other ways to decline an
  elicitation") says a top-level `"decision": "block"` declines, and that `reason`, `systemMessage`
  and `continue` are discarded. The vendored JSON had `top_level_decision_enum: null`. Both JSON files
  corrected. Those two events were on the permissive fallback response schema, which REJECTS a
  top-level `decision` (the latent trap in N374 item 11), so they now have bespoke schemas
  (`_elicitation_schema`). `systemMessage` stays declared (the daemon's loud contract-substitute
  carries it) with two dead-letter ALLOWLIST entries.
- `UserPromptSubmit` now documents the `session_title` input; added as a conditional input field.
- `PostToolUseFailure` per-event section no longer shows `decision`, but the top-level decision table
  still lists it, so the JSON stays.
- Notification `quota_auto_resume_*` types and `DirectoryAdded` sources are already handled.

`META.json` (fetch date, bytes, sha, `last_audited_claude_code_version` 2.1.296 = installed) and both
pinned tests moved. `TestAgreesWithContractMeta` relaxed from `==` to "newest recorded release not
ahead of META" because a refresh between releases cannot also invent a release record.
`test_new_session_on_the_audited_version_is_silent` stubs the review-drift half (reviews are at
2.1.293). Checks: `check_hook_contract.py` and `check_input_contract.py` clean.

## N374 residuals

| Item                                                              | Outcome                                                                               |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| per-file `git check-ignore` in `find_under`                       | fixed: memoised per base within a call                                                |
| autonomy re-detects runtime per event                             | fixed: uses `ProjectContext.container_runtime()`, detects only when uninitialised     |
| fallback response schema rejects top-level `decision`             | fixed for the two affected events + guard test over all fallback events               |
| `sensitive_content` re-reads fake-values.yaml                     | fixed: handler-side cache keyed on (mtime_ns, size); `utils/fake_values.py` untouched |
| `cli.py` hard-coded `"completed"`, duplicated pattern compilation | NOT done: `daemon/cli.py` was off limits                                              |

## N333 - left Open (owner decision)

Facts: the ceiling pause exists to stop a session before a real limit. If one is hit anyway, Claude
Code's wait and auto-continue are already recorded (`quota_resume_recorder` -> `limit_events`) and
re-briefed at the next prompt (`limit_rebrief`). The pause record expires at the window reset plus a
grace hour. Whether an auto-continued prompt that lands inside a live pause should be denied by
`usage_pause_gate` or left through is a policy choice, and Claude Code's behaviour at that moment
is not documented. Question for the owner: leave auto-continue alone (today), or hold it behind the
pause until `resume_at`?

## N335 - compared

`/doctor prompt-audit` (skills doc, "Check your setup with /doctor"; 2.1.283+) is an on-demand,
model-run review of CLAUDE.md files, skills and agents for outdated or conflicting instructions.
`skill_scan` mines session transcripts for skill-creation opportunities (different input, different
output). `docs_qa` is deterministic, tracked-doc drift checking at edit and commit (pointers,
duplicates, quote drift, rule files). Complementary, no duplicated duty. The one-off run against this
repository needs an interactive session and was not done.

## Tests

Red before fix: 5 (response schemas) + 2 (autonomy) + 1 (fake-values cache) + 1 (find_under) = 9.
All green after. Touched-area runs: tests/unit/core, tests/unit/qa/test_check_hook_contract.py,
the contract staleness and version-record tests, protected-file-index, autonomy and sensitive-content
files; ruff and black clean; mypy clean on touched src.
