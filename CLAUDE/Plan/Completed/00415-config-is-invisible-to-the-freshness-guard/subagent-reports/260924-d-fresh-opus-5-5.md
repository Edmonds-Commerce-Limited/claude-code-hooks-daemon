# Delivery report: Plan 00415 (d-fresh, Opus 5.5)

Branch `worktree-d-fresh`. Commits: `ebe7161e` (detector and RED tests),
`56a42686` (fix). Plan 00414 was delivered on the same branch (`7632d265`); see
its own report.

## Reproduction (against unchanged code)

- `cmd_check_source_fresh` exited 0 ("Daemon source is fresh") after the
  project's `hooks-daemon.yaml` was edited under a daemon that still reported
  its startup fingerprint.
- `compute_current_project_fingerprint` raised `ValueError` on a YAML syntax
  error. It caught only `FileNotFoundError` and pydantic's `ValidationError`, so
  "a freshness check never crashes on a broken config" held only for schema
  errors.

## Rulings (recorded in PLAN.md beside each question)

1. Hash the resolved config model as canonical JSON, not the file.
2. A separate `config_fingerprint`, with every consumer reading one
   combined-verdict helper.
3. A config that fails to load hashes to the `config-parse-failed` sentinel.

## Per-task outcomes

| Task                                | Outcome                                                                                                                                                                                                                                                           |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.1 settle the questions            | Done: the three rulings above.                                                                                                                                                                                                                                    |
| 1.2 read 00371 and 00395            | Done. 00371 deferred to `daemon_restart_verifier`, which advises at commit time and so never reaches a harness grading a live dispatch before a commit. 00395 deferred to 00389, which reconciles only after `git pull`.                                          |
| 1.3 failing test, not the detector  | Fixed. RED committed in `ebe7161e`. The key behaviour test is `tests/unit/daemon/test_cli_check_source_fresh.py::TestCmdCheckSourceFresh::test_config_edited_without_restart_exits_one`, with `test_config_unchanged_is_fresh_on_every_run` for the no-flap half. |
| 1.4 implement and prove determinism | Fixed. `tests/unit/daemon/test_config_fingerprint.py::TestComputeConfigFingerprint::test_identical_across_separate_processes` covers three processes with different `PYTHONHASHSEED` and working directories (`/`, repo root, `/tmp`).                            |
| 1.5 consumer sweep                  | Fixed. 3 instances: `daemon/cli.py:1245`, `tests/acceptance/conftest.py:172`, `tests/acceptance/test_daemon_source_freshness.py:40`. `smoke_test` inherits the verdict through `check-source-fresh`. The health payload now carries `config_fingerprint`.         |

Success criteria 1 to 4 are met and verified live (below). Criterion 5 (full QA
plus CI) is left for the coordinator's gate over the merged batch.

## Defence Before Fix

- **Class**: a consumer reads ONE fingerprint out of a daemon's health payload
  and judges freshness on it alone, so the input it skipped drifts unseen.
- **Detector**: semgrep rule `freshness-verdict-read-piecemeal`
  (`scripts/qa/semgrep/freshness-verdict.yaml`). It runs in the existing
  `semgrep` gate and fails that gate. The message names the fix. It is pinned by
  `tests/unit/qa/test_semgrep_freshness_verdict.py` against the planted fixture
  `tests/fixtures/semgrep/freshness_verdict_reads.py`.
- **Proof**: it fired on the originating instance `daemon/cli.py:1245`, and was
  committed red before the fix.
- **Sweep**: two techniques, the rule over `src`/`scripts`/project-handlers
  and grep over `tests/`. Count: 3, all fixed. After the fix the rule finds 0.
- **Finding worth keeping**: the first draft used a `$KEY` metavariable with a
  `metavariable-regex` filter. In a directory scan it TIMED OUT on
  `daemon/cli.py`. Semgrep reports a timeout as a warning and exits clean, so
  the gate would have passed while blind to the one real instance. The shipped
  rule uses literal keys, which let semgrep skip non-matching files. The same
  risk may apply to other rules in `scripts/qa/semgrep/` that use generic
  metavariable filters on large files. `run_semgrep_check.sh` does not treat
  `errors[].type == "Timeout"` as a failure. That is a toolchain gap I did not
  fix here.
- **Scope limit**: the semgrep gate scans `src` and `scripts`, not `tests/`, so
  a future test-side consumer is caught only by review. The rule's own header
  says so.

## Live verification (worktree daemon)

- After a restart, `check-source-fresh` reported both fingerprints as fresh.
- A comment-only edit to the config read FRESH three runs in a row.
- `idle_timeout_seconds: 600` changed to `601` read `STALE DAEMON: the config it bound at startup (config_fingerprint d612bbe8e2bd) does not match the config on disk as it resolves now (562fc489cff5)` and exited 1.
- A YAML syntax error was refused by the CLI's own config load with a named
  "Invalid configuration" error and exit 1, not a traceback. The library
  function returns the sentinel (unit-tested). The CLI never reaches it, because
  project-path resolution already fails fast on such a config.
- After the revert it read FRESH again. `tests/acceptance/test_daemon_source_freshness.py`
  passed against the live daemon (3 tests), and `smoke_test` passed 3/3.

## Files changed

- `src/claude_code_hooks_daemon/daemon/source_fingerprint.py`
- `src/claude_code_hooks_daemon/daemon/controller.py` (`config_fingerprint`
  parameter, health key)
- `src/claude_code_hooks_daemon/daemon/cli.py` (`cmd_check_source_fresh`,
  `_build_initialised_controller`)
- `scripts/qa/run_smoke_test.sh` (comments only)
- `scripts/qa/semgrep/freshness-verdict.yaml` (new)
- `tests/acceptance/conftest.py`, `tests/acceptance/test_daemon_source_freshness.py`
- `tests/unit/daemon/test_config_fingerprint.py` (new),
  `test_cli_config_fingerprint_wiring.py` (new), `test_cli_check_source_fresh.py`,
  `test_controller.py`, `test_source_fingerprint.py`
- `tests/unit/daemon/test_cli_cmd_start.py`, `test_cli_start_reuse.py`: 7 tests
  hand `_build_initialised_controller` a `MagicMock` config, which cannot be
  hashed. Each now sets `model_dump.return_value = {}`.
- `tests/unit/qa/test_semgrep_freshness_verdict.py`,
  `tests/fixtures/semgrep/freshness_verdict_reads.py` (new)
- Release note 52.

## QA run (targeted, per the wave rules)

`format lint type_check pyright magic_values error_hiding shell_check semgrep docs_qa plan_qa handler_reference british_english smoke_test` all passed.
pytest: `tests/unit/daemon`, `tests/unit/handlers/session_start`,
`tests/unit/qa` and the staging-file tests passed (3507 in the broad run). The
only errors in that run were the live acceptance freshness tests, which
correctly reported STALE because I edited source while it ran. They passed
after a restart. `repo_hygiene` reports 2 `plan-stats-arithmetic` findings in
`CLAUDE/Plan/README.md`. They are present on main, and I was told not to edit
that file.

## Not changed, and why

- No config key changed, so there is no config-changes entry. I added no
  truth-change for 00415: no project document is likely to assert that
  `check-source-fresh` covers code only.
- `describe_fingerprint_mismatch` was removed rather than kept as a
  deprecated alias. A public half-check is exactly what the ruling forbids.
