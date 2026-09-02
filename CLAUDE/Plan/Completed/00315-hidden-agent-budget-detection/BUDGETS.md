# BUDGETS.md — the hidden budget catalogue (Task 1.3 synthesis)

Synthesised from the Task 1.1 documentation sweep
(`subagent-reports/260902-claude-code-guide-docs-sweep.md`), the Task 1.2
transcript mining of ~589 MB of session archive
(`subagent-reports/260902-transcript-miner.md`), and the field-relayed
search-budget fixture (JOURNAL/ 2026-09-02 entry).

**Honesty note on sources.** The Task 1.1 sweep drew mostly on THIS
repository's code and docs, not a live sweep of Anthropic's public
documentation — so its "NOT FOUND in public docs" claims mean "not found in
this corpus", a weaker statement. Where the source of truth is our own code,
the limit is a DAEMON-imposed limit, not a harness budget; the two layers
are separated below because the daemon can change one and only ever react
to the other.

## Layer 1: Harness budgets (Claude Code / API side — we can only react)

| Budget                          | Ceiling / default                                                       | Source of truth                                                                                          | Failure shape                                                                                                           | Hook-visible?                                                                                              |
| ------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Web search budget               | 200 WebSearch calls **per session**; env `CLAUDE_CODE_MAX_WEB_SEARCHES` | Field fixture only (verbatim, another machine); locally never hit; no doc link found                     | System message REPLACES the search result: "Web search was not performed: this session has used its web search budget…" | **Unknown** — needs one live confirmation of whether the replacement reaches the PostToolUse tool_response |
| WebFetch limits                 | Unmapped — no ceiling, no fixture, no doc found                         | None (zero evidence in 589 MB)                                                                           | Unknown                                                                                                                 | Unknown                                                                                                    |
| API overload / rate limit       | n/a (server-side)                                                       | Transcript: "API Error: 529 Overloaded"                                                                  | API-stream assistant text, retried by harness                                                                           | **No** — never enters the tool layer                                                                       |
| 5-hour / weekly usage limits    | Account-tier                                                            | Transcript: "You've hit your session limit · resets …" + structured `quotaLimits: {"status":"rejected"}` | API-stream text + the one machine-parseable budget field found anywhere                                                 | **No** — API stream, not a hook event                                                                      |
| Bash tool_result output cap     | ~200–286 KB observed                                                    | Transcript (20 occurrences)                                                                              | `<persisted-output>` + "Output too large (NKB). Full output saved to: <path>" + 2 KB preview                            | **Yes** — literal tool_result content, stable sentinel                                                     |
| File/attachment line truncation | varies                                                                  | Transcript (202 occurrences)                                                                             | `… [N lines truncated] …`                                                                                               | Mostly attachment-borne; partially visible                                                                 |
| Subagent return channel         | ~96k chars observed breakage (Plan 00307)                               | Plan 00307 dogfood reproduction                                                                          | **SILENT** mid-content cut, no marker                                                                                   | **No** — only size-based inference works                                                                   |
| Context window / auto-compact   | 200k (or 1M) window                                                     | Harness-documented behaviour; tiers tracked by our status line                                           | Auto-compact event                                                                                                      | Yes via status-line payload (`used_percentage`)                                                            |

## Layer 2: Daemon-imposed limits (ours — configurable, documented in code)

Subagent report size gate (4k chars, `subagent_report_size_blocker`), hook
handler timeouts (5s/30s), Bash timeouts, background-task TTL/CPU advisory
thresholds, plan document size caps, log rotation, transcript tail buffer.
These are not "hidden budgets" — they are our own guardrails with config
keys and source files; the Task 1.1 report tables them fully. Excluded from
the detector question.

## Build / no-build verdicts

- **BUILD (cheap, evidence-backed): Bash output-cap advisory.** The
  `<persisted-output>` / "Output too large" sentinel is stable, hook-visible
  and carries the persisted-file path; a PostToolUse advisory can tell the
  agent "your full output is at <path>, read selectively, do not re-run".
  20 archive occurrences say it happens in practice.
- **HOLD: web-search-budget detector.** The trigger fragments are stable
  ("Web search was not performed", "web search budget" — never key on the
  configurable "200"), but whether the replacement text reaches a
  PostToolUse hook payload is unverified and cannot be verified from the
  archive (zero native occurrences). Ship the pattern only after ONE live
  confirmation — which will happen organically the next time any session
  here exhausts the budget; deliberately provoking it is ruled out.
  Cheapest interim: document `CLAUDE_CODE_MAX_WEB_SEARCHES` for
  research-heavy sessions.
- **NO BUILD: quota/rate-limit detection.** 529s, session/usage limits and
  `quotaLimits` rejections never traverse hook events; the failsafe
  recovery cron (Plan 00298) is already the correct mitigation layer.
- **NO BUILD (already built): subagent channel.** The silent elision has no
  marker; size-gating at SubagentStop (Plan 00307) is the only workable
  detection and it exists.
- **NO BUILD: WebFetch.** Nothing to match; revisit only if a fixture ever
  appears (the miner's patterns are on file for re-running).

## Open questions for the owner checkpoint

1. Build the Bash output-cap advisory now (small, fixture-driven), or park
   the whole plan as research-complete until a live search-budget fixture
   arrives?
2. Should the daemon document the harness budgets it cannot detect (a
   short section in the generated CLAUDE.md guidance) so agents stop
   retrying against invisible walls even without a detector?
3. Occurrence ledger: worth shipping alongside any detector, or defer?
