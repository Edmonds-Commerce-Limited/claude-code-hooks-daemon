# Fact check: NIGGLES.md N544 (Plan 00474)

(The requested path /workspace/subagent-reports/ is refused by the markdown-location guard, so the report is in the plan's subagent-reports/ folder.)

| #   | Claim                                                                                                      | Verdict             | Evidence                                                                                                                                                                        |
| --- | ---------------------------------------------------------------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | The assertion in tests/acceptance/test_playbook_harness.py already names each disagreeing probe            | VERIFIED            | test_playbook_harness.py:321 appends `#{test_number} {handler_name}: {outcome}` per mismatch; :323-326 asserts `not failures` with the joined list as the message               |
| 2   | scripts/qa/run_changed_tests.py keeps a red run's pytest output tail as `pytest_output`                    | VERIFIED            | run_changed_tests.py:961-962: `if not tests_green: report["pytest_output"] = output[-KEPT_OUTPUT_MAX_CHARS:]` (negative slice = tail)                                           |
| 3   | The cap is `KEPT_OUTPUT_MAX_CHARS`                                                                         | VERIFIED            | run_changed_tests.py:92 `KEPT_OUTPUT_MAX_CHARS: Final[int] = 200_000`                                                                                                           |
| 4   | The docs-or-code tier in .github/workflows/qa.yml uploads `untracked/qa/` when the job fails               | VERIFIED            | qa.yml job `targeted` is named "QA (docs or code tier)"; step "Upload QA output" has `if: failure()`, `actions/upload-artifact@v4`, `path: untracked/qa/` (about lines 189-197) |
| 5   | Before the change the run "kept only failing test names and CI kept nothing"                               | VERIFIED (narrowly) | The report's `tests` list holds only name and outcome; commit f6385c619 touches both files                                                                                      |
| 6   | The handler #140 changed (`supervisor_indicator`) declares one trivial context probe accepting any message | UNVERIFIABLE-HERE   | A grep for `supervisor_indicator` under src/hooks_daemon found nothing; tests/fixtures/cyber-flag was not searched (guard-blocked)                                              |
| 7   | CI run 40424574049 on 2234dc879 failed once and passed on re-run                                           | UNVERIFIABLE-HERE   | CI history not queried (no `gh` call)                                                                                                                                           |

## REFUTED

None.
