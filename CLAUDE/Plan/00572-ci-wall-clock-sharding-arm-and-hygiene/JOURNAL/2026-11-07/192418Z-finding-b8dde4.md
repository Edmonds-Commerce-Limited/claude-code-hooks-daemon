## 19:24 · finding · —   — Phases 1-2 merged; release-slate regression fixed

Phases 1 and 2 merged to main at 4b1317734 through PR #178. Every check passed and CI exercised the new workflows: `test-shards.yml` and the `full` profile.

The first `release-slate-check` after the merge found a regression from the job rename. `release_slate.py` matched jobs by the old `QA (Python` prefix, so no run could ever count as full-tier green, and every release would have been blocked at Step 1a. Task 1.5 now keys the check on the two full-tier groups, `QA static (Python` and `Full suite / `. Each group must be present and entirely successful.

A new test in `tests/integration/test_ci_job_timeouts.py` ties both prefixes to the full-tier jobs declared in `qa.yml`, so a future rename fails a test instead of silently blocking a release. Run against the old `release_slate.py`, 9 of 86 tests fail. With the fix, all 86 pass.

The first main pushes after the merge also showed Task 1.3 working: the runs for fa205141f, 4b1317734 and b5dc2104a were all live at the same time, and none was cancelled.
