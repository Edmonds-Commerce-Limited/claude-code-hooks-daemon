# Plan 00478 Task 2.2a: implementer report

## Shared helper

`claude_code_hooks_daemon.utils.unknown_verdict`: `unknown_verdict_allow(guard, cause, rephrase) -> GatingResult` (ALLOW, one advisory line in `context`, one WARNING log line `UNKNOWN-VERDICT <guard> <cause>`), plus `unknown_verdict_line` and the constant `UNKNOWN_VERDICT_LOG_PREFIX`. Blank arguments raise `ValueError`. No existing equivalent was reusable: `secret_file_guard._literal_finding_or_advisory` and `project_containment._advise_not_judged` build handler-specific results and log nothing greppable. Later batches call it unchanged. `utils/staging_simulation.py` gained `INCOMPLETE_SIMULATION_REPHRASE` (replacing the unused `INCOMPLETE_SIMULATION_BLOCKED`). Test support: `tests/support/unknown_verdict_asserts.py` (`assert_unknown_verdict`: ALLOW, no rule, guard and needles in the advisory, exactly one log line).

## Routes converted (INVENTORY rows 6-13)

| Row | Handler                                              | Result                                                                                                                                                            |
| --- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 6   | `conflict_marker_commit_gate` timeout                | advisory; rule ID `R-CONFLICT-MARKER-SCAN-TIMED-OUT` is kept and re-described as "ADVISORY ONLY" (it is still in `get_rules()` and is cited in the advisory text) |
| 7   | `conflict_marker_commit_gate` unplaceable/unreadable | advisory                                                                                                                                                          |
| 8   | `sensitive_content` unreadable word list             | advisory naming the path from the error, never a term                                                                                                             |
| 9   | `sensitive_content` staging simulation fails         | advisory                                                                                                                                                          |
| 10  | `staged_lint_gate`                                   | advisory in block AND warn mode                                                                                                                                   |
| 11  | `remote_docs_commit_gate`                            | advisory                                                                                                                                                          |
| 12  | `docs_qa_commit_gate` block mode                     | advisory                                                                                                                                                          |
| 13  | `plan_qa_commit_gate` block mode                     | advisory                                                                                                                                                          |

## Positive findings are not lost

- `conflict_marker_commit_gate` no longer returns on the first unknown commit. It records the unknown, keeps scanning every commit in the command, and denies on any finding; it warns only when nothing was found. Test: `test_an_unplaceable_later_commit_does_not_hide_a_marker_in_an_earlier_one`.
- `sensitive_content` row 9: the old code let `SimulationIncompleteError` escape from `_bash_haystacks`, discarding the command-text haystacks. The staged-tree part now yields an `unchecked` marker haystack and the command text (commit message, `gh` body, message files) is still scanned. Test: `test_a_term_in_the_message_still_denies_when_the_staging_cannot_be_simulated`. Row 8: with no terms readable no secret-term finding is possible; public patterns are checked first and still deny (`test_a_public_pattern_match_still_denies_when_the_list_is_unreadable`).
- Every existing positive-match deny test is unchanged and passing.

## Tests

- RED seen: `test_unknown_verdict.py` (ModuleNotFoundError at collection); conflict gate (`test_a_directory_outside_any_repository_is_an_advisory_not_a_silent_allow` AssertionError against the old deny); remote docs (`NameError: name 'unknown_verdict_allow' is not defined` on the first run of its new test). For rows 8, 9, 10, 12, 13 I wrote the tests and the implementation in the same pass and did not capture a separate RED run; this is a TDD lapse, stated plainly.
- Rows 11-13 have new handler-level tests (warn and block modes for 12 and 13).
- `test_a_failing_grep_allows_with_a_visible_advisory` now really asserts ALLOW. The acceptance test "a commit it cannot place" now expects ALLOW (`TestType.ADVISORY`), and `test_the_dry_run_command_would_deny_were_dry_run_misjudged` stages a marker so the deny is a real finding.

## Rule text

`get_claude_md()` of `conflict_marker_commit_gate` and the `_TIMED_OUT_RULE` text no longer say "fails closed" or "denied"; the `_REPHRASE` text no longer says "stays denied". `sensitive_content`'s comment on the deny headline was narrowed to the NUL-byte case. Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/027-...md` (026 is taken on the #173 branch).

## Disagreements and notes

- Out of scope and left alone: `sensitive_content.scan_text` (a CLI helper for `remote-docs`, not a hook) still reports an unreadable word list as a finding.
- The brief's "TDD first for every route" was not fully met (see Tests).
- I was warned that my context passed the soft budget; I continued because the remaining work was small.

## Review fixes

Commit a2a7f5687, from the review `261110-task-2-2a-review-code-reviewer.md`.

1. **CRITICAL, a found marker lost to a later git failure.** RED first: the three new `TestAFoundMarkerSurvivesALaterUnreadablePart` shapes failed 4 of 7 (`assert ALLOW == DENY`, for the within-commit diff failure and the second-grep failure, each as a timeout and as a non-timeout failure); the cross-commit shape and the pure timeout already passed. Fix: `_grep` returns the output read so far with the failure, `_candidate_lines` and `_findings` return `(findings, problems)`, and a failing `_added_line_numbers` or `_whole_text` ends only its own path. `handle` denies on any finding and warns for the problems. A pure timeout with nothing found still allows with the advisory. The other converted handlers (sensitive_content, staged_lint, remote_docs, docs_qa, plan_qa) have no such shape: `simulated_staging` raises only before it yields, and sensitive_content returns every deny before it reaches the advisory (pinned by the existing message-term and public-pattern tests).
2. **IMPORTANT, stale deny wording.** `docs/guides/HANDLER_REFERENCE.md` and the `rule_ids.py` comment now say allow with an advisory. No other deny wording for these routes was found in the reference. `CLAUDE.md`'s generated rule table regenerates on restart.
3. **SUGGESTION, advisory wording.** `unknown_verdict_line` now reads "could not fully decide, so it allowed this call; not checked: <cause>". sensitive_content carries a rephrase per cause and joins only those present. Tests were written before the change; I did not run them red separately.

QA: `42/42 PASSED` (`changed --range main..HEAD --allow-unmapped`), after one RUF012 lint finding in my new test was fixed. `tests/integration/test_pending_release_notes_holding_area.py` passes.
