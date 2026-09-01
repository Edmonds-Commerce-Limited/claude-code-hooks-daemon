# Plan 00307 — Task 1.1 reproduction findings (RED)

## Dispatch (repeat VERBATIM for the Phase 4 GREEN acceptance re-run)

Agent tool, `model: haiku`, no tools used by the agent, prompt:

> This is a harness-behaviour test probe (Plan 00307 Task 1.1 in /workspace).
> Your ONLY job is to return a deliberately enormous final message so we can
> observe how the harness delivers it to the coordinator.
>
> Instructions:
>
> 1. Do NOT write any files. Do NOT use any tools at all.
> 2. Compose your final message as follows: start with the exact line
>    "PROBE-START", then produce numbered sections "SECTION 0001" through
>    "SECTION 0400", each section being 3 lines of varied technical filler
>    prose (do not repeat the same sentence — vary wording so it cannot be
>    compressed/summarised), and end with the exact final line
>    "PROBE-END-MARKER-7391".
> 3. Return ALL of it inline as your final message. Do not summarise, do not
>    truncate yourself, do not stop early — the entire point is to exceed any
>    output cap and see what arrives.

## What the coordinator received

- The final message arrived INLINE in the coordinator's context, in full bulk
  (~24k subagent tokens; the notification landed as one giant blob).
- **The payload WAS truncated by the harness, in the MIDDLE**: an explicit
  elision marker `... [2301 characters truncated] ...` appeared inside the
  report (mid-way through SECTION 0115, resuming inside SECTION 0122 —
  roughly seven sections lost). This is harness behaviour, not the model:
  the surrounding sections are intact and the marker text is not something
  the probe was asked to produce.
- Both sentinels (`PROBE-START`, `PROBE-END-MARKER-7391`) survived, which
  means an end-marker check alone does NOT prove an intact report — the
  harness elides the middle, so a coordinator can receive a report that
  LOOKS complete (starts and ends correctly) while silently missing content.
  This matches the owner's field report of agents "returning a truncated
  message" and the failures being confusing to diagnose.
- Secondary observation: the model also self-degraded under output pressure —
  later sections shrank from the requested 3 full prose lines to 1–2 short
  lines, i.e. long inline reports decay in quality even before the harness
  cuts them.

## Consequences pinned for the design

1. Middle-elision means truncation is NOT reliably detectable by the
   coordinator; prevention/enforcement must happen on the subagent side
   (SubagentStop) and at dispatch, not by coordinator-side inspection.
2. Even the surviving bulk is pure coordinator context tax — the file-handoff
   norm pays off below the cap too.
3. Threshold guidance: the observed harmful shape was a ~24k-token final
   message; the enforcement threshold should sit far below that (a final
   message should be a summary + path — on the order of a few hundred
   tokens; exact configurable default to be set in Phase 3 and tuned in
   Phase 4 dogfood).

## GREEN criteria for the Phase 4 re-run

Re-issue the dispatch above verbatim after Phases 2–3 land. Pass =
dispatch-time contract injected AND the oversized inline return blocked at
SubagentStop until the agent writes the report to a file and returns a short
summary + path; no elision marker ever reaches the coordinator.

## GREEN re-run result (Task 4.1) — PASS

Same dispatch, verbatim, with `dispatch_declaration` (advisory) and
`subagent_report_size_blocker` (threshold 4,000 chars) live:

- The probe generated 84,877 characters (312 sections) and attempted the
  inline return. **The SubagentStop blocker fired**: the probe's own report
  confirms the harness "detected output exceeded 4,000-character threshold"
  and the stop-hook guidance instructed redirecting to a file.
- **The probe complied**: full output written to
  `untracked/260901-probe-harness-test-haiku.md` (it noted its first-choice
  location was rejected and it fell back to an allowed markdown path); the
  final message returned to the coordinator was a ~1,100-character summary
  - the file path. No elision marker, no truncated blob, no context flood.
- Notable: this happened despite the probe being ORDERED not to write files
  or use tools — the block redirected it anyway (two tool uses recorded).
  Enforcement beats instructions, which is exactly the property we wanted.

Tuning inputs for Task 4.2 (dogfood):

1. The probe landed the file at `untracked/` root with its own name, not
   the configured fallback `untracked/agent-reports/` nor the
   `{yymmdd}-{agent-name}-{model}.md` convention path the guidance should
   steer toward — the block reason's path guidance can be more prescriptive.
2. The markdown-location handler rejected its first write location; the
   size-blocker's remediation should name a location that is always
   writable, so the two handlers never argue.
