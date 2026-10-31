# Fact check: N566 entry in NIGGLES.md (Plan 00474)

Scope: claims added by the diff `untracked/plan-fact-check/00474-niggles-ledger-seventeen.diff`. The diff touches only NIGGLES.md; PLAN.md is unchanged by it.

## REFUTED

None.

## Notes

- The journal entry says the evaluator "twice rejected" an `[awaiting-human]` stop. N566 says "six times". That is a transcript-count claim and cannot be checked here. The journal was written earlier in the session, so the two numbers are not necessarily in conflict.
- `session_mode_registry.py:142-143` says without the supervisor a human must type `/goal clear`. The "never goes idle" mechanism is therefore the entry's inference, not something the repo documents.

## Table

| #   | Claim                                                                                                                    | Verdict                     | Evidence                                                                                                                                                                                                                                 |
| --- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | The journal entry `131551Z-decision-c83609.md` exists                                                                    | VERIFIED                    | `CLAUDE/Plan/00555-self-install-venv-python-version-lockout/JOURNAL/2026-10-31/131551Z-decision-c83609.md` exists. It is a decision entry saying the goal was retracted with `bin/hooks-daemon clear-goal`.                              |
| 2   | `bin/hooks-daemon clear-goal` exists                                                                                     | VERIFIED                    | `src/claude_code_hooks_daemon/daemon/cli.py:12601-12612` registers the `clear-goal` subparser. `cmd_clear_goal` is at `cli.py:5584`. `bin/hooks-daemon` is present.                                                                      |
| 3   | `clear-goal` queues a retraction that the supervisor types as `/goal clear`                                              | VERIFIED                    | `cli.py:5650` prints "Goal retraction queued ... the supervisor types /goal clear." `clear_goal_signal` (`goal_injection.py:592`) removes the goal-intent file and writes a `.goal-clear` trigger.                                       |
| 4   | The retraction waits for the supervisor to type `/goal clear` "at its next idle"                                         | VERIFIED                    | `core/session_mode_registry.py:102-104` and `:142-143` use that wording.                                                                                                                                                                 |
| 5   | The goal-loop detector put the session in goal-blocked mode and told it to run `clear-goal`, journal the reason and stop | VERIFIED (instruction part) | `GOAL_LOOP_SELF_CLEAR_INSTRUCTION` at `session_mode_registry.py:105-111` says to run `clear-goal`, journal the reason, and stop with the real blocker. That the detector fired in this session is a transcript event: UNVERIFIABLE-HERE. |
| 6   | The session ran all three steps                                                                                          | VERIFIED (journal)          | The journal entry exists and says the goal was retracted with `clear-goal`.                                                                                                                                                              |
| 7   | Tasks 2.5 and 2.6 of Plan 00555 are still unticked                                                                       | VERIFIED                    | The 00555 PLAN.md has `- [ ] ⬜ **Task 2.5**` at line 102 and `- [ ] ⬜ **Task 2.6**` at line 109.                                                                                                                                       |
| 8   | The goal's stop-hook evaluator rejected `[awaiting-human]` stops six times with the same reasoning                       | UNVERIFIABLE-HERE           | Session transcript event. The journal says "twice". Settle it from the session transcript.                                                                                                                                               |
| 9   | Each rejection costs a full model turn and the session never goes idle                                                   | UNVERIFIABLE-HERE           | Behavioural claim about the transcript and the supervisor.                                                                                                                                                                               |
| 10  | Source: "dogfood, 2026-10-31, in the session working Plan 00555"                                                         | VERIFIED (consistent)       | The journal is dated 2026-10-31 under Plan 00555.                                                                                                                                                                                        |

Tally: 10 claims: 8 verified, 0 refuted, 2 unverifiable (claim 5 is partly a transcript event and is counted as verified on its repo-checkable part).
