# Fact check: Plan 00501 Phase 0 diff

Result: 14 claims, 12 verified, 0 refuted, 2 verified with drift notes.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Mid-turn `/goal clear` takes effect at once (7 supervisor injections) | VERIFIED | decision.log lists the 7 timestamps; transcript goal_status sentinel met:true within ms (22:50:32.504, 06:52:21.030, 08:02:39.208, 19:04:05.579) |
| 2 | 9 idle `/goal clear` are local_command records | VERIFIED | 9 `/goal` clear command records |
| 3 | goal_status counts sentinel 175/100, unmet 28/79, met 16/12 | VERIFIED | jq: 172+3, 93+8 (101, live file grew by 1); unmet 28/79; met 16/12 |
| 4 | All stop_hook_summary preventedContinuation:false (2,072+3,090) | VERIFIED (drift) | jq: 3090 and 2078, all false; transcript has grown |
| 5 | Six cap events on 2026-10-11, five followed by Goal paused, 13:58 not | VERIFIED | six timestamps 13:01..14:38; Goal paused at 13:01,13:03,13:39,14:28,14:38 |
| 6 | 129 `Goal set:` queued_command (84/45) | VERIFIED | jq 84 and 45 |
| 7 | Claude Code cap is 8 continuations, override env CLAUDE_CODE_STOP_HOOK_BLOCK_CAP | VERIFIED | hooks.md:2765, changelog.md:6429; spike's "9th block" consistent |
| 8 | stop-events totals 794/444/4264/933 | VERIFIED (drift) | now 795/444/4268/933 (live log) |
| 9 | Goal-clear cap 5 per process, `_GOAL_CLEAR_COMMAND` :2882, cap :2883, :7748 | VERIFIED | claude-supervise.py lines match; 2 "cap reached" no-ops in log |
| 10 | can_inject gate :7253 is human idleness; `_is_idle` 6941, `_is_work_idle` 6952; busy no-op 7747 | VERIFIED | code read |
| 11 | 16 "own line still in the input box" no-ops | VERIFIED | grep count 16 |
| 12 | Docs lines 439, 1087, 2424, 2758 quoted | VERIFIED | awk of hooks.md |
| 13 | `_log_stop_event` call sites 822-926; block-marker stand-down 765-779 | VERIFIED | grep; note: line 1260 is `_log_stop_event`, not `matches()` (spike wording loose, matches() is at 731) |
| 14 | "No autonomy doc exists yet" (Task 7.1) | VERIFIED | git ls-files finds no autonomy doc under docs/ or elsewhere (only Plan 00498 files, code and tests) |

Unverifiable here: 2.1.212/2.1.296 changelog fix wording not rechecked beyond the entries existing; live `continue:false` result (spike itself says unproven); the "inferred" ordering claim in spike 0.2 section 3 (marked inferred by the spike).

REFUTED: none.
