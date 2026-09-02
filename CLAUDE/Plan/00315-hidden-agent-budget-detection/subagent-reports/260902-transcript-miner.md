# Task 1.2 — Transcript mining for budget-shaped tool errors

Corpus: 13 JSONL transcripts under `/root/.claude/projects/-workspace/` (~589 MB,
sessions 2026-08-03 → 2026-09-02) plus one sibling scratchpad project dir
(`-tmp-claude-0--workspace-…-scratchpad-measure-empty/`, one small transcript).
All searches were targeted `rg` extractions; no transcript was read whole.
Self-referential matches (this plan's own prompts, the daemon's handler prose
and test fixtures, which use "budget"/"rate limit" heavily as vocabulary) were
identified and excluded from the counts below.

## 1. WebSearch/WebFetch budget-exhaustion refusals — ZERO hits

No occurrence of "search budget", "no more searches", or any
WebSearch/WebFetch error, refusal or limit message exists in the archive
outside this plan's own discussion text. Every "search budget" match (16) is
the user's report or plan prose about the phenomenon, not an observed error.
Absence is the finding for the LOCAL archive: no native occurrence exists here,
so the shape below is field-confirmed elsewhere, not locally observed.

**Field-confirmed fixture (from another machine's session, relayed by
team-lead; a targeted grep for it here finds only 5 relays of that same
quotation inside the current Plan 00315 session, zero native hits).** Verbatim:

> "Web search was not performed: this session has used its web search budget
> (200 of 200 WebSearch calls). Continue with the information already gathered
> instead of issuing more searches. If more searches are genuinely needed,
> [raise CLAUDE_CODE_MAX_WEB_SEARCHES]"

Pinned facts: the cap is **per-session** ("this session"), default **200
WebSearch calls**, configurable via the **`CLAUDE_CODE_MAX_WEB_SEARCHES`**
environment variable, and it recurred on every subsequent search attempt
(41 occurrences in the source transcript). Delivery: a **system message
replacing the search result** — visible in the turn/transcript, but as a
result-replacement rather than a tool error field. Because it substitutes for
the WebSearch result itself, a PostToolUse hook on WebSearch is the natural
observer IF the replacement text flows through the hook's tool_response
payload; that needs one live confirmation, since our archive contains no
native event to verify the JSON field against. Stable trigger fragments for a
detector: `Web search was not performed`, `web search budget`,
`CLAUDE_CODE_MAX_WEB_SEARCHES`, `of 200 WebSearch calls` (the count varies
with the configured ceiling, so prefer the first two).

## 2. Rate-limit / overloaded / quota shapes — FOUND, none in tool_result

All of these arrive as **assistant-message content, system events, or teammate
notifications — never as a tool_result**, so an in-session PostToolUse hook
would see none of them. They are visible only in the transcript (or to a
Stop/Notification-level observer).

### 2a. API Error: 529 Overloaded

Verbatim: `API Error: 529 Overloaded. This is a server-side issue, usually temporary — try again in a moment. If it persists, check https://status.claude.com.`

- Field: `message.content[].text` of a synthetic **assistant** message
  (5 occurrences), and `failureReason` of a teammate **idle_notification**
  with `"idleReason":"failed"` (3 occurrences; timestamps 2026-08-17,
  2026-08-18). Further mentions are agents discussing a peer that died this way.
- Producer: the API stream itself / a dying teammate session — no tool.

### 2b. Session/usage limit (quota rejection)

Verbatim assistant text: `You've hit your session limit · resets 9:50am (UTC)`
(2 occurrences, 2026-08-26). Uniquely, these assistant messages carry a
**structured** sibling field:

```json
"quotaLimits":{"status":"rejected","resetsAt":1787737800,
  "unifiedRateLimitFallbackAvailable":false,"rateLimitType":"five_hour",
  "overageStatus":"rejected","overageDisabledReason":"org_level_disabled",…}
```

This is the only machine-parseable budget signal found anywhere in the
archive. Related events from the same episode:

- System event, `"type":"system","subtype":"informational"`:
  `Usage limit reached · continuing automatically at 9:50am · esc or type to cancel` (1) and `Automatic continue cancelled · /rate-limit-options to re-arm` (1).
- Teammate idle_notification `failureReason: "You've hit your session limit · resets 9:50am (UTC)"` (1).
- Prose records a subagent that "died on a session limit mid-task" (Plan
  00274 prototype agent); the main thread resumed its work — i.e. the limit
  killed the agent silently from the coordinator's point of view.

### 2c. Other API-stream failures (same channel, not budget but same shape class)

- `API Error: Unable to connect to API (ENOTIMP)` — 14, assistant content text.
- `API Error: Sonnet 5 can't help with this. Start a new session to continue.`
  — assistant text and idle_notification failureReason (a refusal presented in
  the API-error channel).
- `API Error: Response stalled mid-stream. The response above may be incomplete.` — idle_notification failureReason.

HTTP 429 as an error never appears (the 4,712 raw "429" matches are all hex
IDs/UUIDs). No `rate_limit_error` JSON type, no `prompt is too long`, no
"exceeds maximum tokens" tool_use_error anywhere.

## 3. Output truncation markers — FOUND, and these ARE hook-visible

### 3a. `<persisted-output>` (Bash output cap)

Verbatim shape (20 occurrences, sizes 41.5 KB–286.2 KB):

```
<persisted-output>
Output too large (216.8KB). Full output saved to: /root/.claude/projects/-workspace/<session>/tool-results/<id>.txt

Preview (first 2KB):
…
```

- Field: `tool_result` **content** (string), `is_error: false`.
- Producer: Bash (previews show `gh run watch`, grep sweeps, ls output).
- **A PostToolUse hook sees this** — it is the literal tool_result content.
  The `<persisted-output>` sentinel plus "Output too large (…)" is a reliable,
  stable trigger string.

### 3b. `… [N lines truncated] …` (attachment/file-read cap)

Verbatim: `\n\n... [292 lines truncated] ...` — 202 occurrences, N ranging
~40–693.

- Field: inside `"type":"attachment"` payload content (file-read attachments),
  occasionally quoted inside tool_result text.
- Producer: the harness's file/attachment renderer, not a tool call the model
  made — mostly **transcript-only** from a PostToolUse perspective, though the
  same marker appearing inside a Read/Bash tool_result would be visible.

## 4. Subagent return-channel elision — no verbatim marker exists (it is silent)

No harness-emitted elision marker was found. What the archive does contain:

- The daemon's own `dispatch_declaration` PreToolUse:Agent advisory quoting
  "a subagent's return travels over a bounded-size channel that silently
  elides an oversized inline report" — self-produced guidance, not evidence.
- Plan prose recording "a live-reproduced harness bug where an oversized
  inline subagent final message is silently elided in the middle" — i.e. the
  failure leaves **no marker at all** in the elided text. There is nothing for
  a hook to pattern-match; detection would have to be size-based (measure the
  Agent tool_result), which is exactly why `subagent_report_size_blocker`
  exists.

## 5. Other limit/quota/budget shapes — nothing further

Remaining "budget"/"limit exceeded"/"quota" matches (~1,000 lines) are all
this repository's own vocabulary: timeout budgets in tests, the
module-doc-budget handler, plan-index navigability limits, recovery-cron
prose about usage limits, and the sensitive-content "quotation" false
friends. No additional error shape emerged. The 13 small Aug-26 transcripts
correspond to the session-limit episode in 2b.

## Summary table

| #   | Shape (verbatim trigger)                                | Field                                            | Producer      | Count                    | PostToolUse-visible?         |
| --- | ------------------------------------------------------- | ------------------------------------------------ | ------------- | ------------------------ | ---------------------------- |
| 1   | `Web search was not performed: … budget (200 of 200 …)` | system message replacing the search result       | WebSearch     | 0 local; field-confirmed | Likely — needs live confirm  |
| 2   | `API Error: 529 Overloaded…`                            | assistant content text; idle_notif failureReason | API stream    | 8                        | No                           |
| 3   | `You've hit your session limit · resets …`              | assistant content text + `quotaLimits` object    | API stream    | 2                        | No                           |
| 4   | `Usage limit reached · continuing automatically…`       | system informational event                       | harness       | 1                        | No                           |
| 5   | `API Error: Unable to connect to API (ENOTIMP)`         | assistant content text                           | API stream    | 14                       | No                           |
| 6   | `<persisted-output>` / `Output too large (NKB)`         | tool_result content, is_error=false              | Bash          | 20                       | **Yes**                      |
| 7   | `... [N lines truncated] ...`                           | attachment payload                               | file renderer | 202                      | Mostly no (attachment-borne) |
| 8   | Subagent inline-report elision                          | none — silent mid-report cut                     | Agent return  | n/a                      | No marker; size-check only   |

Practical upshot for the detector design: the budget-adjacent signals a
PostToolUse hook can plausibly catch are the Bash `<persisted-output>` cap, a
size check on Agent returns, and — pending one live confirmation of the
payload field — the WebSearch budget-refusal system message (shape 1). Every genuine quota/rate-limit event in this
archive bypassed the tool layer entirely, surfacing as API-stream assistant
text (with `quotaLimits` as the one structured field) or as teammate
idle-notifications — channels a Stop/SessionStart/Notification observer, or a
transcript tailer, would need to watch instead.
