# Plan 00326 — Web-tool hook payloads (Task 0.1)

Empirically captured, not inferred. Nothing in this repository documented
these shapes: the vendored contract is organised per EVENT rather than per
TOOL, `BUDGETS.md` recorded WebFetch as "Unmapped — zero evidence in 589 MB",
and `untracked/payload-capture/` was empty.

**Method**: `daemon.payload_capture` enabled for `PreToolUse`/`PostToolUse`,
daemon restarted (not Claude Code), one `WebFetch` of `https://example.com`
and one `WebSearch`, then `untracked/payload-capture/*.jsonl` read. Capture
was turned off again immediately afterwards — it records *every* payload for
those events, which is not something to leave running.

**Captured against**: Claude Code v2.1.259, daemon v3.61.0.

## The headline: `WebFetch` does NOT deliver the fetched document

`tool_response.result` is the **small fast model's answer to your `prompt`**,
not the page. The fetched markdown never reaches the hook at all.

```json
{
  "bytes": 559,
  "code": 200,
  "codeText": "OK",
  "result": "The primary heading on this page is \"Example Domain.\"",
  "durationMs": 1003,
  "url": "https://example.com"
}
```

`https://example.com` is 559 raw bytes; what arrived was one sentence. This
is D2's summarisation hazard confirmed by measurement rather than by
argument — there is no route from a `WebFetch` to the document it fetched,
so a capture path built on it could only ever store a paraphrase.

It also settles D15 with evidence rather than reasoning: the dropped
PostToolUse offer-to-vendor was never merely redundant, it was **impossible**.
There is nothing to vendor. The same applies to the transcript fallback
(`TranscriptReader.get_tool_result_text_by_id`) — it would recover this same
`result` string, because that string *is* the tool result.

`bytes` is the one genuinely useful field: raw upstream size without the
content.

## `WebFetch` — `PreToolUse.tool_input`

```json
{
  "url": "https://example.com",
  "prompt": "What is the single main heading on this page? Answer in under 10 words."
}
```

**`tool_input.url` is the field Task 5.1 keys on.** This was the only
remaining gate in D11, and it is now closed.

## `WebSearch` — `PreToolUse.tool_input`

```json
{ "query": "Claude Code hooks PostToolUse tool_response schema" }
```

Only `query` was present. `allowed_domains` / `blocked_domains` exist in the
tool schema but are absent when unset, so any consumer must treat them as
optional rather than assuming a fixed key set.

## `WebSearch` — `PostToolUse.tool_response`

Keys: `query`, `results`, `searchCount`, `durationSeconds`. `results` is an
array of `{tool_use_id, content}`, where `content` is an array of
`{title, url}` — eight entries here.

Titles and URLs only; **no page content**. So a search yields candidate URLs
but nothing vendorable, which is consistent with D14's conclusion that the
deterministic checkpoint belongs at the downstream `WebFetch`.

## Top-level envelope (both events, both tools)

`PreToolUse`: `cwd`, `effort`, `hook_event_name`, `permission_mode`,
`prompt_id`, `session_id`, `tool_input`, `tool_name`, `tool_use_id`,
`transcript_path`.

`PostToolUse`: the same plus `duration_ms` and `tool_response`.

Two of these were flagged against the vendored contract: **`effort`** and
**`prompt_id`**. `PostToolUse.json` documents `duration_ms`, which is
present as documented.

**Resolved in Task 0.2, and the original claim was half wrong.**
`prompt_id` IS listed in `PreToolUse.json`'s `input_example` — only `effort`
was absent. And the gap was not deliberate: `effort` is documented upstream
verbatim (hooks.md — "Object with a `level` field holding the effort level
in effect when the hook runs … Present for events that fire within a
tool-use context, such as `PreToolUse`, `PostToolUse`, `Stop`, and
`SubagentStop`"). It was therefore added to those four `input_example`s,
sourced from the raw markdown as the refresh procedure requires — never
from the observed payload alone, which would record an undocumented field
as if documented.

## What this changes in the plan

- **Task 5.1 is unblocked**: key on `tool_input.url`.
- **D15 is upgraded** from a design judgement to a measured fact.
- **D2's premise is confirmed**: `WebFetch` output is a model answer.
- **No task should ever read `tool_response.result`** expecting document
  content.
