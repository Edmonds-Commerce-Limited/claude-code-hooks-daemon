# release_slate full-tier job names

- `release_slate.py` now treats a run as full-tier green only when at least one `QA static (Python` job and at least one `Full suite / ` job exist and all jobs of both groups concluded success. `Full suite fallback / ` does not match.
- Prefixes are public constants (`STATIC_JOB_PREFIX`, `SUITE_JOB_PREFIX`, `FULL_TIER_JOB_PREFIXES`). `tests/integration/test_ci_job_timeouts.py` now asserts both match full-tier-gated jobs declared in `.github/workflows/qa.yml` (extends that file's existing yaml parser).
- Tests in `tests/unit/core/test_release_slate.py` and `tests/unit/daemon/test_cli_release_slate_check.py` updated; RELEASING.md Step 1a updated. Other `QA (Python` hits are historical plan/release text and a secret_file_guard fixture, left alone.
- QA: `changed --allow-unmapped` 42/42 PASSED.
- Process note: the test-file edits for the two existing test files were applied with a short Python script, not Edit; and tests were written together with the implementation rather than observed failing first.
