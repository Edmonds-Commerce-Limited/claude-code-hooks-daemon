# Plan 00479 fact check: first-real-pause record, Phase 6, owner question 5

Scope: the claims the diff adds. Transcript facts were checked by grepping timestamps and record numbers in the main
session transcript (line numbers below are records in `c61663f0-....jsonl`), never read whole.

Result: 17 claims: 14 verified, 2 refuted, 1 unverifiable.

## REFUTED claims, most consequential first

### R1. "the session replaced its crons with the resume cron through real `CronDelete`/`CronCreate` calls. Steps one and two are observed." (Success Criteria)

Refuted for the main transcript. The only `CronDelete`/`CronCreate`/`CronList` `tool_use` blocks anywhere near the pause are
`CronList` at record 12746 (2026-10-08 15:00:16Z, after the owner's clear) and `CronDelete`/`CronCreate` in that same
15:00 turn, which restore the crons the pause had removed. Between the deny at 14:52:36Z (records 12632-12641) and the
clear at 14:59:50Z there is no assistant turn at all (records 12642-12690 hold zero assistant messages). Earlier cron
calls are at record 11066 (2026-10-08 04:18Z), long before the pause. So the transcript shows the gate denying tools and the
pause directive naming the swap, but no model-issued swap. The investigation report does not claim one either: it only
says the owner's clear output states the crons "were replaced by the pause".
Change to the plan: say that the pause entry (deny, directive, supervisor `/compact`) was observed, and that the cron swap
by the model was NOT observed (the model had no turn before the owner cleared). Drop "real CronDelete/CronCreate calls" and
"Steps one and two are observed", or name what other evidence shows the swap. This also affects the tick-ability of the
live-observation item, which the plan leaves open.

### R2 (partial). "the first prompt after the window reset re-read usage and released the session" (On 2026-10-10 the gate did lift a later pause by itself)

The lift is real: record 26441, 2026-10-10 09:35:24Z, hook context "USAGE PAUSE LIFTED - usage is back under the ceiling",
on the prompt `[tick:job:issue-sdlc]` (record 26440). The "after the window reset" part is not supported and conflicts with the
plan's own open fact. The pause that was lifted had been entered at 2026-10-09 23:35 with a stated resume of
2026-10-11 08:02 UTC (supervisor message, record 26300), about 22.5 hours AFTER the lift. The directive says only "back under
the ceiling", not "the window reset". The journal's wording ("on the first prompt after the reset") is the same unsupported
inference.
Change to the plan: say "usage was back under the ceiling" and that the lift came about 22.5 hours before the recorded reset
of 2026-10-11 08:02. That is more evidence for the open fact about the provider's window moving, so link it to owner question 5's
"related open fact".

## Claim table

| #   | Claim                                                                                                                 | Verdict           | Evidence                                                                                                                                                                                                                                      |
| --- | --------------------------------------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Report path `subagent-reports/261010-p479-first-real-pause-sonnet.md` exists                                          | VERIFIED          | `ls` of the plan's `subagent-reports/` lists it                                                                                                                                                                                               |
| 2   | First real pause at 2026-10-08 14:52 UTC                                                                              | VERIFIED          | Deny records 12632-12641 stamped 2026-10-08T14:52:36Z                                                                                                                                                                                         |
| 3   | The seven-day window reached 80%                                                                                      | VERIFIED          | Deny text: "seven_day window at 80% (ceiling 80%)"                                                                                                                                                                                            |
| 4   | The gate denied tools                                                                                                 | VERIFIED          | `R-USAGE-PAUSE-TOOL` deny at 14:52:36Z (records 12632-12641)                                                                                                                                                                                  |
| 5   | Session replaced its crons via real `CronDelete`/`CronCreate` calls; steps one and two observed                       | REFUTED           | See R1                                                                                                                                                                                                                                        |
| 6   | Owner lifted the pause with `! bin/hooks-daemon usage-pause clear`, so the resume tick was not observed               | VERIFIED          | `<bash-input>` record 2026-10-08T14:59:50Z; no `[tick:usage-resume]` prompt reached the model after it                                                                                                                                        |
| 7   | On 2026-10-10 the gate lifted a later pause by itself                                                                 | VERIFIED          | Record 26441, 09:35:24Z, "USAGE PAUSE LIFTED"; code path `_hold_or_lift` in `handlers/user_prompt_submit/usage_pause_gate.py:173-179` re-checks the ceiling on every held prompt                                                              |
| 8   | ... "first prompt after the window reset"                                                                             | REFUTED (partial) | See R2                                                                                                                                                                                                                                        |
| 9   | "the owner's override (`usage-pause clear`) suppressed the ceiling silently until the breaching window's reset"       | VERIFIED          | `usage_pause.py` `usage_override_active` is only `now < until`; `until` was 2026-10-09 23:00 per the clear output; the override handling logs only (report Q3)                                                                                |
| 10  | "On 2026-10-08 it was written at 80%"                                                                                 | VERIFIED          | Same pause at 80% and clear at 14:59:50Z                                                                                                                                                                                                      |
| 11  | "Usage then rose unobserved to the account's hard limit"                                                              | VERIFIED          | Supervisor message 2026-10-09 23:35 shows PAUSED again with resume 2026-10-11 08:02; 429s with "session or weekly limit" text in records about 26200-26320                                                                                    |
| 12  | "three working agents died mid-task on HTTP 429"                                                                      | VERIFIED          | Three distinct 429 request ids in the `task-notification` summaries (two sonnet-5-5, one opus-5-5) with `<status>failed</status>` and "died on a session or weekly limit". The journal adds a reviewer; the count of agents is at least three |
| 13  | "The behaviour matches the docs"                                                                                      | VERIFIED          | `handlers/user_prompt_submit/usage_pause_gate.py:287` ("override until the latest reset among the windows over the ceiling (at most ...") and the clear command's own text, "even if usage is still over the ceiling"                         |
| 14  | Absence of any override visibility today (premise of Task 6.1: no `override until HH:MM` chip, no per-prompt context) | VERIFIED          | `grep -rn "override until\|override_until" src` finds only the clear-command text at `usage_pause_gate.py:287`; no status-line handler mentions it                                                                                            |
| 15  | "the live seven-day reset (2026-10-11 08:02) differed from the reset the override trusted (2026-10-09 23:00)"         | VERIFIED          | Supervisor message record 26300 (10-11 08:02); override end 10-09 23:00 in the clear output (record at 15:00:00Z)                                                                                                                             |
| 16  | "On 2026-10-09 the owner renamed the alias to `github-softwaredev-lifecycle-unattended`"                              | VERIFIED          | `git log -S` finds commit ca426bdef, 2026-10-09 12:12:50 +0000, "Rename the SDLC runner role alias ... (owner decision)"; the name is in `.claude/hooks-daemon.yaml:1457,1756` and `CLAUDE/development/IssueSdlc.md:477`                      |
| 17  | Option (b) "for example 95%" and the head-room rationale; options (c), (d)                                            | UNVERIFIABLE-HERE | These are proposals, not facts about the tree. The report's candidate fixes list the same ideas (hard threshold such as 95%, rise of N points above the clear-time level, per-window scope). Nothing to check beyond that                     |

## Notes

- The override cap is `MAX_PAUSE_SPAN_SECONDS = 8 * 86400` (`usage_pause.py:79`), applied in `write_usage_override`
  (`usage_pause.py:266-295`), consistent with what the plan implies.
- The plan journal entry (JOURNAL 26-10-10, 09:43) repeats R2 and says "swapped its crons ... with real calls", which is R1. Both
  need correcting entries if the plan text is fixed.
