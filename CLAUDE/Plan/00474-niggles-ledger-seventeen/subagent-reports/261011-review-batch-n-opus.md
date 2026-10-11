STOPPING BECAUSE: review complete. Verdict: CHANGES REQUIRED.

# Review: batch N (4ebd40273 against main)

All 351 targeted tests pass: response_schemas, check_hook_contract, version_record, contract_staleness, autonomy, protected_file_index, sensitive_content_fake_values and hook_result. Probes are in `/workspace/untracked/scratch/review-batch-n/`.

## Required

**1. The N375 refresh missed a new input field, `mcp_server` (confidence 90%).**
- The fetched raw doc (`<worktree>/untracked/scratch/hooks-raw.md`) says at line 1699 that MCP-tool calls now carry `mcp_server {name, source}`. It needs Claude Code v2.1.274 or later, so it arrived after the 2.1.272 audit.
- The doc tells hooks to "Base trust decisions on `source` rather than on `name` or the `mcp__<server>__` tool-name prefix". That makes it relevant to security.
- It appears on PreToolUse (1699), PermissionRequest (2031), PostToolUseFailure (2237) and PermissionDenied (2352).
- No contract JSON mentions it (grep of `contracts/` finds only `mcp_server_name` in Elicitation*).
- So two claims in the report and the ledger are false: "field names and enums match" and that every per-event JSON was read on the input side. The ledger marks N375 "✅ Fixed" on the strength of them.
- **Fix:** add `mcp_server` to `conditional_input_fields` in those four JSON files, citing line 1699. Then do step 5 of HOOK-CONTRACT-REFRESH.md: classify it as consumed or as a recorded gap, with a ledger item if it is a gap.

**2. Correct the N375 ledger and report text** (`NIGGLES.md` N375 status, `subagent-reports/261011-batch-n-sonnet.md` §N375) once item 1 is done.
- A diff of backticked tokens against the 2026-09-16 raw copy (`/workspace/untracked/scratch/hooks-raw.md`, saved one day after the audit) also turns up `onFailure` (hook config, v2.1.295, raw lines 461 and 515).
- It also turns up the Stop hook's 8-consecutive-continuation cap (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`, raw line 2683). This matters to the daemon's Stop re-block handlers.
- Neither is recorded anywhere. At minimum each needs a triaged ledger entry.
- The report's "the previous raw text is not kept" is only partly true: that 09-16 copy existed in the main checkout. It is not byte-identical to the audited 322902 bytes, but it was close enough to diff.

## Checked and sound

- **Provenance (1):** the worktree's raw file is exactly 266649 bytes with sha256 `3a1f9445…`, matching META.json, which fits the `contract-status --save` workflow. remote-docs is not the procedure for this contract; HOOK-CONTRACT-REFRESH.md is, and it does not track the raw body.
  - Every quote added to the Elicitation, ElicitationResult and UserPromptSubmit notes appears in the raw doc (lines 3612, 3783, 1442). One small difference: the doc has backticks around `action`.
  - `last_audited_claude_code_version` 2.1.296 is the installed version (`claude --version` gives 2.1.296), which is what step 3 of the procedure asks for. That the changelog review stops at 2.1.293 is a separate track, and the ledger says so.
- **Relaxed test (2):** equality could not hold between releases unless a release record were invented, because every recent record is `unknown`. The `<=` check still fails on the real problem: a release recorded as tested on a Claude Code newer than the audited contract. The contract-staleness stub narrows that test to the contract half only, and the ledger states the review-drift advisory will still fire.
- **Schema (3):** matches the doc.
  - `decision` is limited to `block` (doc line 1113).
  - `action` accepts only accept, decline and cancel; `content` is an object.
  - `reason` and `continue` are rejected; `systemMessage` is kept as a recorded dead letter.
  - No handler emits a block on these events. Their bases are AdvisoryHandler, so a DENY goes through `_format_system_message_response`, gives `{"decision":"deny"}`, and is replaced by the loud `systemMessage`, which validates.
- **Caches (4):**
  - `find_under`'s memo lives for one call only, so it cannot go stale.
  - The container runtime cannot change while the process lives.
  - The fake-values cache key includes the path; stamp and value sit in one attribute, so threads cannot pair them wrongly. A file that is missing gets `(0,0)` and is picked up once it appears.
- **N333 (5):** the question is put neutrally, states current behaviour, and claims no ruling. N335 is fine.

## Non-blocking (file as plan tasks)

- **a.** `core/hook_result.py:76`: Elicitation and ElicitationResult can now carry a block, but they are not in `_TOP_LEVEL_BLOCK_EXTRA_EVENTS` or `REFUSAL_CAPABLE_EVENTS`.
  - If they are wired in later, `_format_top_level_block_response` adds `reason`, which the new schema rejects. That turns the block into a substitute that does not enforce it.
  - **Fix:** decide whether to wire them. If yes, drop `reason` for these events and add a test.
- **b.** `contracts/claude-code-hooks/Elicitation*.json` notes: record raw line 3618. Claude Code ignored a top-level `decision` on these events from v2.1.105 until the fix in v2.1.284, which matters for clients on older versions.
- **c.** `sensitive_content.py` `_registry_stamp`: a rewrite of the same size within the filesystem's timestamp resolution keeps a stale allow-list until the next change. The risk is low; a short comment saying so is enough.
- **d.** `tests/unit/core/test_response_schemas.py`: the fallback guard test builds its contract path with `parents[3]`. That is fragile but correct today.