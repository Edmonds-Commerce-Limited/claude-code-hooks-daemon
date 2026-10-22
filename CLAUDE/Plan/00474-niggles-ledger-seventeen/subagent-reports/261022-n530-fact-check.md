# N530 fact check

Diff: /workspace/untracked/plan-fact-check/00474-niggles-ledger-seventeen.diff. Only the N530 claims were checked.
Handler: src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_number_helper.py
Probe: untracked/scratch/n530_probe.py, which runs `matches()` with plan dir `CLAUDE/Plan`. Output is in untracked/scratch/n530_out.txt.

## REFUTED

**R1. "`ls CLAUDE/Plan/00501-session-modes/subagent-reports/ | grep -iE "spike|loop"` was denied as R-PLAN-NUMBER-DISCOVERY."**

On the current tree the handler does NOT match this command. The probe printed `False` for it, and also for the bare `ls` of that folder.

Rule by rule (line numbers are in plan_number_helper.py):

- mkdir rule: no `mkdir` in the command.
- wc exemption (536): not applicable, and nothing else matches either.
- Rule 1, `_ls_globs_plan_folders` (340-365): the path component is `00501-session-modes`. It must match `\*|0\*|\[0-9\]` (line 358) and does not, so it is skipped.
- Rule 2, find: not present.
- Rule 3, echo/printf: not present.
- Rule 4, sort and tail: no `sort`.
- Rule 5 (647-650): `ls\s+.*CLAUDE/Plan` and `grep` are both present. The second regex, `grep.*['"]?\^?\[?0-9\]?`, needs the literal `0-9` AFTER `grep`. `"spike|loop"` has none, so it fails. The `00501` sits before `grep` and does not count.

The probe printed `True` only when the grep pattern contained `[0-9]`. That is, `... | grep -iE "spike|loop|[0-9]"` was denied, and so would `grep '^[0-9]'`.

What this changes in the plan: the N530 entry's Source line says the reported command was denied, but the command text as recorded cannot be the one that was denied. Either the grep pattern held a digit class that was not recorded, or a different handler or a different tree state was involved. The Expected and Fix direction text is still sound for the shape that does trip Rule 5: a grep with a digit pattern over a listing of a path below an `NNNNN-name/` folder. Rule 5 judges only "ls somewhere under the plan dir, plus grep with `0-9`", not the listed target. Before the fix is TDD'd, fix the entry so the reproduction is a command that actually denies. Do not use the recorded one as the "allowed case"; it is already allowed.

## Table

| #   | Claim                                                                                          | Verdict                           | Evidence                                                                                                                                                                                                                 |
| --- | ---------------------------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | The reported command was denied as R-PLAN-NUMBER-DISCOVERY                                     | REFUTED                           | Probe: `matches()` is False. Rule 5 needs `0-9` after `grep` (line 649).                                                                                                                                                 |
| 2   | The deny names the next number (00550)                                                         | VERIFIED                          | `git config --local hooksdaemon.latestPlanNumber` is 549. `handle()` (678-689) prints "Next plan number is ..." from `next_plan_number_for_target`. 00550 is consistent with a counter of 549; I did not run `handle()`. |
| 3   | Only a listing of the plan root (or Completed/) can discover plan numbers                      | VERIFIED                          | This is the semantics of the glob rules (`_ls_globs_plan_folders`, find at line 590).                                                                                                                                    |
| 4   | The handler denies on a listing below a plan folder (the N530 premise)                         | VERIFIED, narrower than stated    | Probe: True for `ls CLAUDE/Plan/00501-session-modes/subagent-reports/ \| grep -iE "spike\|loop\|[0-9]"`. The cause is Rule 5, which does not look at the listed target.                                                  |
| 5   | The folder is `CLAUDE/Plan/00501-session-modes/`                                               | VERIFIED                          | `ls -d CLAUDE/Plan/00501*` shows the directory.                                                                                                                                                                          |
| 6   | Fix direction: deny only when the target is the plan root or an archive directory              | UNVERIFIABLE-HERE (design)        | Rule 5 would be the place to change, not Rule 1. Rule 1 already skips a specific plan folder.                                                                                                                            |
| 7   | STATUS-INDEX row N530 repeats the verdict                                                      | VERIFIED, with the claim 4 caveat | The row says "(its `subagent-reports/`)" and omits the grep.                                                                                                                                                             |
| 8   | N526 recurrence (cba846ee3, 95aba97b5, run 39819035114, report 261022-n526-recurrence-opus.md) | Out of scope                      | The diff changes it, but you asked for N530 only. Not checked.                                                                                                                                                           |

Totals for the N530 claims (rows 1-7): 4 verified, 1 refuted, 1 unverifiable (row 6), plus one caveat on row 7.

## Re-check

Scope: the corrected N530 entry and its STATUS-INDEX row. Probe: untracked/scratch/n530_probe2.py, which runs `matches()` with plan dir `CLAUDE/Plan`.

| # | Claim | Verdict | Evidence |
| - | ----- | ------- | -------- |
| 1 | `ls CLAUDE/Plan/00501-session-modes/subagent-reports/ \| grep -iE "spike\|loop\|0\.[0-9]"` is denied | VERIFIED | Probe `matches()` is True for the exact command. |
| 2 | The `ls \| grep` rule fires on a `[0-9]` class in the grep pattern | VERIFIED | Rule 5, plan_number_helper.py:647-650, needs the literal `0-9` after `grep`. The same command with `0\.3` and the original `spike\|loop` both give False. |
| 3 | The rule never looks at the listed path | VERIFIED | Line 647 only requires `ls\s+.*CLAUDE/Plan` somewhere in the command. A path below a plan folder passes it. `ls /tmp \| grep "[0-9]"` gives False, so the dependency is on the plan-dir text, not on the target. |
| 4 | Fix direction: allow whatever the grep pattern holds | UNVERIFIABLE-HERE (design) | The change belongs in Rule 5. |
| 5 | The `0.3` in the pattern is a spike number | UNVERIFIABLE-HERE | Parenthetical, no file to check. |
| 6 | The fact-check file exists at that path | VERIFIED | This file. |
| 7 | STATUS-INDEX row: `subagent-reports/` piped to a grep holding `[0-9]`; the rule ignores the listed path | VERIFIED | Same evidence as rows 2 and 3. |

Totals: 5 verified, 0 refuted, 2 unverifiable. The earlier R1 refutation is resolved by the corrected command text.
