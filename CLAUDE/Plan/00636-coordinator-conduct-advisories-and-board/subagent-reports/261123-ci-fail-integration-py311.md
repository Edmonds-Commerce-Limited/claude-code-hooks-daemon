# CI failure: Full suite / tests py3.11 integration (PR #226, run 45215360517)

Verdict: INCONCLUSIVE. Not yet classified as flake or real; no fix, no rerun made.

Evidence:

- Job 137835318297 (head 1f310a732): `integration: FAILED 7855 passed, 2 failed in 664.3s`. The runner log (`run_test_matrix.py`) prints only counts, not the two test ids, and the check-run annotations carry only "exit code 1".
- Not a timeout: 664s wall, no timeout/infra errors in the log.
- Other jobs of the same run (py3.11 acceptance-and-other, py3.13 pre-tool-use, QA static x3) passed. py3.12 and py3.13 integration were still in progress when I looked.
- Local narrowed run in the worktree (py3.13 venv, integration tests matching claude_md/doc_truth/declared_behaviour/acceptance/every_handler/all_handlers/handler_reference/example_config/stop): no failure through ~89% before my 590s cap killed it. Filter was a guess, so this does not clear the branch.

Why I stopped: `gh run rerun --failed` is refused while the run is in progress, and the two test ids are unknown.

Next step: when run 45215360517 completes, check py3.12/py3.13 integration. The same 2 failing on those = real branch failure (then rerun locally on the same shard under py3.11). Failing on 3.11 only = `gh run rerun 45215360517 --failed` and see whether it recurs. To get the test ids, rerun with `-rf` visible or run `python scripts/qa/run_test_matrix.py --shard integration` locally under py3.11.
