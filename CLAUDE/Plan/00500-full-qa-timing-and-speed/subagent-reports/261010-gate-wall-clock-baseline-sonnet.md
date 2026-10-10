# Gate wall-clock baseline (read-only research)

Source: session transcript /root/.claude/projects/-workspace/c61663f0*.jsonl, the per-step timing tables printed by `llm_qa.py all` (timestamps are when the tool result arrived, UTC). Task 1.2 (timing table) is ae92258cf, 2026-10-07 13:31. Task 3.1 is c02cf9838, 2026-10-09 15:54. Nothing earlier than 1.2 has a table: before it, only matrix legs recorded a duration. No earlier gate total survives in the plan folder, journals or tests.json copies.

## Runs with a full timing table, between Task 1.2 and Task 3.1 (pre-3.1)

| Result at | Command that produced it | total | tests step | Notes |
|---|---|---|---|---|
| 2026-10-08 07:20 | `all --resume` (launched 04:18, many earlier resumes since 10-07 17:08) | 10,897.7 s | 10,463.5 s | Tests complete: 129,365 passed, 0 failed, coverage 95.4%. py3.11 full 5,842.9 s; py3.12 unit 1,573.5 / rest 2,479.4; py3.13 unit 1,547.4 / rest 2,092.9. Gate overall 40/41 (one failure, not tests). Part of a chain of resumed runs after host reboots. |
| 2026-10-09 06:44 | `all --resume` (launched 04:01; fresh `all` started 10-08 23:20, resumed 03:07 and 04:01) | 9,779.8 s | 9,342.5 s | Tests complete: 129,518 passed, 0 failed, coverage 95.4%. py3.11 full 6,535.5 s; py3.12 unit 1,659.7 / rest 2,356.7; py3.13 unit 1,405.9 / rest 2,687.1. Gate 40/41 (one non-test failure). Closest comparable: same matrix (3.11 full + 3.12/3.13 unit and rest), coverage on, about 9 h before Task 3.1 merged. |
| 2026-10-08 00:18 | `all --resume` | 7,566.2 s | not shown in the lines I extracted | Tests step apparently reused/resumed (lint marked reused); NOT comparable as a whole-gate figure. |

Because these were `--resume` invocations, the step wall-clock covers only that invocation's work. A leg finished in an earlier interrupted invocation would not be counted, so the true elapsed time from first start is at least as long. The legs' own durations (e.g. py3.11 full 5,843 s and 6,536 s) are single-leg wall clocks and are the better indicator for the tests step. I did not verify per run whether any leg was restored from a checkpoint.

## Non-comparable

- 2026-10-09 07:51, 17:51 and 10-10 13:43: `changed` / `changed_tests` runs (1,452 s, 1,823 s, 1,753 s tests step; totals 2,797 s and 2,843 s). Different scope, not the full matrix.
- 2026-10-07: the user-quoted figure in PLAN.md (a run over 90 min, tests at 15% after an hour, five reboot-killed runs) has no recorded total.
- Host load for the baseline runs is not recorded in the tables; I did not find load averages. The lock wait (`FULL_QA_LOCK_WAIT_SECONDS=36000`) was in use, so other agents' QA may have queued, but the tables do not separate lock wait from run time (I did not confirm).
- Today's run: `all` at 16:03, result 18:51: total 9,654.8 s, tests 9,266.9 s (then `all --resume` at 18:56).

## Plainly

A comparable pre-3.1 baseline exists only as two resumed complete-tests runs: 10,897.7 s / 10,463.5 s (10-08) and 9,779.8 s / 9,342.5 s (10-09). A non-resumed single-pass pre-3.1 total does not exist. Today's 9,654.8 s / 9,266.9 s is about 1.3 percent below the 10-09 figure and about 11 percent below the 10-08 figure; run-to-run noise on a loaded host is larger (py3.11 full leg ranged 5,843 to 6,536 s). Not judged against the criterion.
