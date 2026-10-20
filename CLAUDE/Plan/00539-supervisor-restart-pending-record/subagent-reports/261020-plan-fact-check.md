# Plan 00539 fact check (diff claims only)

## REFUTED

1. **"Targeted QA is green on the merged head (40/40 on bb7664cbd)"** (Success Criteria).
   The only 40/40 run is in `subagent-reports/261020-issue127-implementer-opus.md:84-88`. It ran on an
   uncommitted worktree tree before the merge, and the report says "It was not recorded for a head".
   No report or journal names bb7664cbd with a QA result. The review fixes f1f763f65 and 7f7046630
   came after that run. Change: drop "on bb7664cbd", or re-run targeted QA on the merged head and
   cite that run.

## Table

| #   | Claim                                                                                            | Verdict  | Evidence                                                                                                                                                                                                                |
| --- | ------------------------------------------------------------------------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Task 1.1 done: record written in `request()` after the last refusal, before `_perform_injection` | VERIFIED | `claude-supervise.py:9296-9318` (focus hold returns at 9306; write at 9310; injection at 9318)                                                                                                                          |
| 2   | Record exists between request and finish/abandon; mode 0600; own session id; wall-clock deadline | VERIFIED | `_write_pending_record` 9208-9232; `_write_private_json` 0600 per triage; 49 tests in `test_plugin_exit_for_restart.py`                                                                                                 |
| 3   | Task 1.2: removed in `abandon()` and `finish()`                                                  | VERIFIED | 9347 and 9370 call `_remove_pending_record`                                                                                                                                                                             |
| 4   | A `finally` in `supervise()` also removes it if the I/O loop raises                              | VERIFIED | `claude-supervise.py:10189-10192` calls `restart.discard_pending_record(log)`; the outer `try` opens at 10162 around the I/O loop. `discard_pending_record` (9234-9241) removes the record only while `_pending` is set |
| 5   | Wall-clock deadline is the backstop for SIGKILL                                                  | VERIFIED | Docstring at 9235-9238; deadline built from `requested_at` (9223)                                                                                                                                                       |
| 6   | Task 1.3: `CCY_SUPERVISOR_RESTART_PENDING` exported in the child env at spawn                    | VERIFIED | `_RESTART_PENDING_ENV` at 9112; `child_environment = {_RESTART_PENDING_ENV: ...}` at 9936                                                                                                                               |
| 7   | `CcySupervisor.md` has an "Exit for restart" section holding the reader contract                 | VERIFIED | `CLAUDE/development/CcySupervisor.md:440` (section), 512-518 (reader contract)                                                                                                                                          |
| 8   | Release note 004 exists in `UNRELEASED/release-notes/`                                           | VERIFIED | `004-supervisor-restart-pending-record-for-session-end-hooks.md`; it cites CcySupervisor.md "Exit for restart"                                                                                                          |
| 9   | Success criteria: no refusal path, focus hold included, leaves a record                          | VERIFIED | Code ordering at 9272-9310; review report line 6 says a test proves this for each refusal                                                                                                                               |
| 10  | bb7664cbd is the merge of `worktree-plan-00539`                                                  | VERIFIED | Two parents (09ca543af, 7f7046630); subject "Merge issue #127..."; implementer report line 4 names branch `worktree-plan-00539`. The branch is deleted locally, so the name is not checkable from refs                  |
| 11  | f1f763f65 holds the review fixes for the review's two suggestions                                | VERIFIED | Subject "review fixes - record removed when supervise() raises; deadline test checks the hold" matches S1 and S2 in `261020-issue127-review-opus.md:14-15`; f1f763f65 is an ancestor of bb7664cbd                       |
| 12  | "The code review approved it"                                                                    | VERIFIED | Review report line 3: "Verdict: APPROVE"                                                                                                                                                                                |
| 13  | Plan 00537 link now points to `../Completed/00537-supervisor-holds-sends-off-main-focus/PLAN.md` | VERIFIED | The file exists at `CLAUDE/Plan/Completed/00537-supervisor-holds-sends-off-main-focus/PLAN.md`                                                                                                                          |
| 14  | Targeted QA green on merged head (40/40 on bb7664cbd)                                            | REFUTED  | See above                                                                                                                                                                                                               |

Note: the diff's "CI is green" half of that line stays unticked, and so is not a claim.

14 claims: 13 verified, 1 refuted, 0 unverifiable
