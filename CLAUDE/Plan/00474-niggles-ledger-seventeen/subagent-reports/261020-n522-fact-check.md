# N522 fact check

| #   | Claim                                                                                                                   | Verdict                | Evidence                                                                                                          |
| --- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 1   | issue-sdlc sets `runs_while_awaiting_human: true` in .claude/hooks-daemon.yaml (Plan 00470)                             | VERIFIED               | .claude/hooks-daemon.yaml:1551,1555; option defined at config/models.py:2259                                      |
| 2   | background-watchdog is declared under persistent_crons with a prompt starting `[tick:watchdog]`                         | VERIFIED               | .claude/hooks-daemon.yaml:1597,1601-1602 (jobs list at :1550)                                                     |
| 3   | The watchdog prompt is not `[tick:job:<name>]`                                                                          | VERIFIED               | same lines; cron_tick.py:10, TickKind.WATCHDOG (line 47) distinct from DECLARED (line 55)                         |
| 4   | failsafe_cron_blockage_suppressor routes non-failsafe ticks to `_handle_other_tick`                                     | VERIFIED               | failsafe_cron_blockage_suppressor.py:336-344                                                                      |
| 5   | `_handle_other_tick` always allows a non-`job:` tick                                                                    | VERIFIED               | same file :424-425 (`kind is not DECLARED` returns ALLOW); docstring :410-412 says the watchdog never stands down |
| 6   | Generated CLAUDE.md says an awaiting-human stop "turns the failsafe cron and every declared `persistent_crons` job off" | VERIFIED               | CLAUDE.md:359                                                                                                     |
| 7   | Generated CLAUDE.md says "every declared job's tick" is dropped                                                         | VERIFIED               | CLAUDE.md:372                                                                                                     |
| 8   | Failsafe ticks were dropped (R-FAILSAFE-CRON-SUPPRESSED)                                                                | VERIFIED (rule exists) | suppressor DENY path :383-385; per-session behaviour is in the diagnosis file, which I did not read               |
| 9   | untracked/scratch/blockage-suppressor-diagnosis.md exists                                                               | VERIFIED               | `ls` found it                                                                                                     |
| 10  | STATUS-INDEX.md has 227 rows                                                                                            | VERIFIED               | 229 table lines minus header and separator = 227 (223 `N` rows plus 4 "entries" rows)                             |
| 11  | 39 rows open                                                                                                            | VERIFIED               | `grep -c "\| ⬜"` gives 39                                                                                        |
| 12  | The N522 STATUS-INDEX row is present                                                                                    | VERIFIED               | The diff adds it; 227 and 39 agree with the file                                                                  |

Not checked: "each idle hour costs two model turns" is an estimate, and the three-stop session history needs the transcript.

REFUTED: none.
