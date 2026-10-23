# Diff fact-check 2: Plan 00474 N531 recurrence

Diff: /workspace/untracked/plan-fact-check/00474-niggles-ledger-seventeen.diff
Evidence: /workspace/untracked/scratch/ci-full-312.log, `gh run view 39883575808`, `gh run view 39874461511`, `gh run view 39853605423`.

## REFUTED

1. "Two of the last two full runs that reached it." (NIGGLES.md N531 Recurred bullet)
   - Run 39874461511 (push, headSha 9939c7a20, 2026-10-22T23:51Z) is a full matrix run. Its QA (Python3.12) job ran 00:03:00Z to 01:50:11Z, which is a full-length run, and concluded success. QA (Python3.11) and QA (Python3.13) also succeeded.
   - It lies between 39853605423 (failed py3.12, 21:00Z on 10-22) and 39883575808 (failed py3.12, 01:22Z on 10-23). So three full runs reached the test and two of the three failed.
   - Fix for the plan: write "two of the three full runs since it appeared" (39853605423 and 39883575808 failed; 39874461511 passed). Without the passing run, the recurrence looks more deterministic than the evidence shows. A flaky-on-load hypothesis fits three runs with two failures.

## Claims table

| #   | Claim                                                            | Verdict  | Evidence                                                                                                                                                                                                                             |
| --- | ---------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Full-matrix run 39883575808 at `106d14543`                       | VERIFIED | `gh run view` gives headSha 106d1454338f050740ec5ce4388429ffaf65d9a4, event workflow_dispatch, conclusion failure. `git cat-file -t 106d14543` returns commit.                                                                       |
| 2   | Job QA (Python3.12) failed                                       | VERIFIED | The job list shows QA (Python3.12) as failure.                                                                                                                                                                                       |
| 3   | The same test                                                    | VERIFIED | The log has `TestProjectRootDoublePatchDoesNotLeakAcrossFiles.test_the_polluter_and_a_victim_pass_together_in_one_process` at line 3205 and `test_project_containment.py:1354` at line 3226. This matches the N531 Source test name. |
| 4   | The same 60 s `TimeoutExpired`                                   | VERIFIED | Log line 3253: `subprocess.TimeoutExpired: Command [... -m pytest -p no:xdist -q ...] timed out after 60 seconds`. The child printed `2 passed in 0.60s` (line 3240).                                                                |
| 5   | At 99% of the run                                                | VERIFIED | The preceding progress lines (3179 to 3199) show [ 99%], then the failure follows at 03:37:59. The final line is `1 failed, 52323 passed ... in 6227.00s` (line 4110).                                                               |
| 6   | Python 3.11 and 3.13 passed                                      | VERIFIED | The job list shows QA (Python3.11) and QA (Python3.13) as success.                                                                                                                                                                   |
| 7   | Two of the last two full runs that reached it                    | REFUTED  | See above. Run 39874461511 was a full run, passed on py3.12, and sits between the two failures.                                                                                                                                      |
| 8   | Status flipped to "in progress" (NIGGLES.md and STATUS-INDEX.md) | N/A      | Plan status, not a claim about the codebase. Not checked.                                                                                                                                                                            |
| 9   | STATUS-INDEX row: "recurred in full run 39883575808"             | VERIFIED | Same evidence as claims 1 to 6.                                                                                                                                                                                                      |
| 10  | STATUS-INDEX Origin is still "main CI run 39853605423"           | VERIFIED | `gh run view 39853605423` shows QA (Python3.12) failed on push at cc49aebbb. This matches the N531 Source line.                                                                                                                      |

## Notes

- The child command in the new run ran `test_project_containment.py::TestEvaluationErrorIsAnAdvisory::test_an_uninitialised_project_root_is_an_advisory` plus `tests/unit/handlers/test_absolute_path.py::...test_handle_omits_the_example_rather_than_guessing_a_root`. Whether this is the identical polluter/victim pair as the first failure is not stated in the diff. The parent test is the same.
- The diff adds a blank line before "Hypothesis to establish first". It is cosmetic.

Tally: 9 claims checked (the status flip is not counted), 8 verified, 1 refuted, 0 unverifiable.
