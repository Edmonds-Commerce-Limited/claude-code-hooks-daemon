# Delivery report: 00466 N21 (d-fresh, Opus 5.5)

Branch `worktree-d-fresh`. N21 went through the same branch as Plans 00414 and
00415 at team-lead's request. I did not edit the ledger (`PLAN.md`,
`NIGGLES.md`); the coordinator owns N21's status row.

## N21: the semgrep gate passed when a rule timed out

- **RED first**: `tests/unit/qa/test_run_semgrep_check.py`. A combinatorial
  rule (`foo(..., $A, ..., $B, ..., $C, ..., $D, ...)`) against a 300-argument
  call, with a 1-second per-rule timeout, forces a real semgrep `Timeout`.
  Semgrep exits 0 and records it only in `errors[]`. Before the fix the gate
  passed. Now it exits non-zero and names the rule and file
  (`test_a_rule_timeout_fails_the_gate_naming_rule_and_file`).
  `test_a_clean_target_still_passes` pins the other direction.
- **Fix** (`scripts/qa/run_semgrep_check.sh`): every `errors[]` entry becomes a
  violation carrying the rule, file and error type, and `summary.error` is
  set. A non-zero semgrep exit or an empty report fails the gate as
  `semgrep-did-not-run`. The previous run's raw output is removed before the
  scan, so a crash cannot re-read stale results
  (`test_a_semgrep_crash_never_reuses_the_previous_runs_output`).
- **A real timeout surfaced at once.** On the unchanged tree the fixed gate
  failed: `bounded-intent-unbounded-read-deferred` (a taint rule) timed out
  on `daemon/cli.py` under parallel QA, at semgrep's 5-second default. It takes
  about 2.2 seconds alone. The old gate had been reporting that file as
  checked. The per-rule timeout is now 30 seconds (`QA_SEMGREP_TIMEOUT`), with
  the reason in a comment. The gate now checks the file and passes.
- Test seams: `QA_SEMGREP_RULES_DIR`, `QA_SEMGREP_OUTPUT_DIR`,
  `QA_SEMGREP_TARGETS`, `QA_SEMGREP_TIMEOUT`.

## The class: a tool error reads as clean

I audited every `scripts/qa/run_*.sh`, `run_*.py`, `check_*.py`,
`check_*.sh` and `audit_*.py` wrapper. Each instance below is fixed and pinned
by a test that fails without the fix.

| Wrapper                                     | Error that read as clean                                                                                                            | Test                                                       |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `run_security_check.sh`                     | bandit crash, bandit `errors[]`, missing report                                                                                     | `tests/unit/qa/test_run_security_check.py`                 |
| `run_lint.sh`                               | ruff exit code other than "findings"                                                                                                | `tests/unit/qa/test_run_lint.py`                           |
| `run_dependency_check.sh`                   | deptry crash, missing JSON, `uv` absent                                                                                             | `tests/unit/qa/test_run_dependency_check.py`               |
| `run_format_check.sh`                       | black exit 123 (internal error)                                                                                                     | `tests/unit/qa/test_run_format_check.py`                   |
| `run_shell_check.sh`                        | SC1091 (shellcheck could not follow a source) was dropped                                                                           | `tests/unit/qa/test_run_shell_check.py`                    |
| `run_pyright_check.py`                      | zero files analysed                                                                                                                 | `tests/unit/qa/test_run_pyright_check.py`                  |
| `check_canonical_callers.sh`                | grep exit 2 and `find` errors                                                                                                       | `tests/integration/test_canonical_callers_static_check.py` |
| `run_tests.sh` + `qa/pytest_text_report.py` | pytest's non-zero exit (coverage threshold, crash after the summary), zero tests run, or a missing JSON report still read as passed | `tests/unit/qa/test_pytest_text_report.py`                 |
| `check_git_history.py`                      | a git error, or zero commits swept; malformed YAML config                                                                           | `tests/unit/qa/test_check_git_history.py`                  |
| `check_sensitive_content.py`                | malformed YAML, an uncompilable pattern skipped, an unreadable file skipped                                                         | `tests/unit/qa/test_check_sensitive_content.py`            |
| `audit_error_hiding.py`                     | an unreadable or undecodable file contributed zero violations                                                                       | `tests/unit/qa/test_audit_error_hiding.py`                 |
| `check_github_urls.py`                      | an unreadable file skipped                                                                                                          | `tests/unit/qa/test_check_github_urls.py`                  |
| `check_skill_references.py`                 | an unreadable file skipped                                                                                                          | `tests/unit/qa/test_check_skill_references.py`             |

Declined, as designed: `audit_error_hiding.py::audit_file` still returns no
findings for a file that does not parse. The `lint` and `type_check` gates
fail that file, so the run as a whole cannot pass over it.

## A second class: skip lists matched the scan root's own ancestors

This is the same outcome, a clean verdict over nothing, from a different
cause. `check_github_urls.py`, `audit_shell.py`, `check_skill_references.py`
and `check_doc_truth.py` skip directories named `untracked` or `worktrees`.
They tested each path's ABSOLUTE parts. A linked worktree lives under
`untracked/worktrees/<name>`, so from any worktree every file matched and the
gates reported "0 violations" over 0 files. All four now judge only the parts
below the root. The three that could scan nothing also fail when they do
(`nothing-scanned`). `doc_truth` always walks the generated handler doc it
needs, so its guard is a test on the real repository (`docs_scanned > 0`).

Measured from this worktree before and after: `github_urls` went from 0 to
4030 files, `shell_audit` from 0 to 62, `skill_refs` from 0 to 696 and
`doc_truth` from 0 to 1771 docs. All four are clean at the new counts.

Tests: `test_a_root_inside_a_skipped_directory_name_is_still_scanned` /
`test_a_sweep_that_scanned_nothing_fails` (github_urls), `TestScansWhatItClaims`
(audit_shell, skill_refs), `test_a_root_below_an_unscanned_name_is_still_scanned`
(doc_truth).

## QA exclusions

None were added. Two stale entries were removed from
`scripts/qa/error_hiding_exclusions.json`: `check_skill_references.py::scan_directory`
and `check_sensitive_content.py::_compile_public_patterns`. Both sites now
report the error instead of skipping it. The `run_shell_check.sh` anchor line
is unchanged. The diff against main for that file has removals only.

## QA run (targeted)

`format lint type_check pyright magic_values error_hiding shell_check semgrep security dependencies canonical_callers git_history sensitive_content github_urls shell_audit skill_refs doc_truth docs_qa plan_qa smoke_test`:
20/20 passed. pytest passed: `tests/unit/qa` (whole directory), the
doc-truth, canonical-callers, declared-behaviour, client-owned-asset-lint, QA
gate-integrity and gate-scope integration tests,
`test_background_harvester.py`, and the hygiene checker's tests.

Release note 63.
