# CI failure diagnosis: PR #228, job acceptance-and-other (run 45216027109, job 137838205257)

Verdict: infra flake, unrelated to the branch (N709 secret-guard bootstrap).

Evidence (from artifact qa-tests-fallback-3.11-3, since job logs are unavailable while the run is in progress):
- 607 passed, 1 failed in 558.94s.
- The one failure is tests/acceptance/test_playbook_harness.py::TestTheDeclaredProbesBehaveAsDeclared::test_every_executable_probe_matches_its_expected_decision_and_reason.
- Reason: "INCONCLUSIVE ... #231 LintOnEditHandler: the Kotlin linter timed out after 15s, so the handler's verdict was never reached". This is the same Kotlin linter timeout seen on earlier acceptance failures.

Action: rerun with `gh run rerun 45216027109 --failed` only once the run has no pending jobs. At the time of writing, the unit, integration-slow and arm64 unit jobs were still in progress, so the rerun was not yet issued.

## Second failure (after the failed-jobs re-run), job 137865375802, 8m1s

Verdict: same Kotlin linter timeout, not a different failure.

Evidence (artifact qa-tests-fallback-3.11-3, tests-py3.11-rest-acceptance-and-other.log): 607 passed, 1 failed, and the one failure is again
tests/acceptance/test_playbook_harness.py::TestTheDeclaredProbesBehaveAsDeclared::test_every_executable_probe_matches_its_expected_decision_and_reason,
"INCONCLUSIVE ... #231 LintOnEditHandler: the Kotlin linter timed out after 15s". The QA gate failure follows from this job.

Load sensitivity: the 15s budget is a wall-clock limit on the Kotlin linter subprocess (playbook_harness.py), so it is sensitive to runner load
(this leg shares a runner with long unit/integration-slow jobs; the first attempt took 558s, the second 368s). The PR diff changes only
secret_file_matching.py (+27/-2) plus tests and docs; it adds no work to the lint path, so it cannot plausibly worsen the timeout. Two occurrences
on the same probe point at a persistently slow Kotlin toolchain start on the runner (a candidate niggle: the Kotlin probe budget is too tight for CI).

Action: all jobs had completed (0 pending), so `gh run rerun 45216027109 --failed` was issued once more.
