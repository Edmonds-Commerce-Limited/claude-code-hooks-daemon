CI triage: run 45176226209, job 137698742765 (py3.11 acceptance-and-other), PR 222

Verdict: flaky or infrastructure, not branch-caused. No code change made.

- Result: 607 passed, 1 failed.
- Failing test: tests/acceptance/test_playbook_harness.py::TestTheDeclaredProbesBehaveAsDeclared::test_every_executable_probe_matches_its_expected_decision_and_reason
- Reason: the gate reported INCONCLUSIVE. Probe #231 (LintOnEditHandler) never reached a verdict because "the Kotlin linter timed out after 15s". It is a timeout under CI load, not an assertion failure.
- Branch diff vs origin/main touches no lint, Kotlin, playbook or acceptance files.
- The same leg passed on PR 223 (run 45171047807, 9m7s).
- Evidence: artifact qa-tests-fallback-3.11-3, file first-error-lines-py3.11-rest-acceptance-and-other.jsonl.
- Action: re-run the failed job.
