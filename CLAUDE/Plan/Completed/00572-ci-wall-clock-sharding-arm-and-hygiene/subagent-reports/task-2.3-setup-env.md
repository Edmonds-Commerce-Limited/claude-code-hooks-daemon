# Task 2.3: composite setup-env action

- Added `.github/actions/setup-env/action.yml` (inputs `python-version`, `venv-location` = fingerprint | project; uv cache via actions/cache keyed on `hashFiles('uv.lock')` + OS + interpreter, replacing `cache: pip`).
- Replaced nine inline copies: qa.yml (targeted, qa matrix, map, perf-sweep, daemon-load), release-gate.yml (x2), test-shards.yml (x2).
- Only real per-job difference: daemon-load used plain `pip install uv` and `./.venv`; kept as `venv-location: project`.
- Untouched: release-assets.yml (PR #183), classify job and the two PyYAML-only jobs (no package install).
- Test: `tests/integration/test_ci_setup_env_action.py` (6 tests); `test_ci_*.py`, tests/unit/qa, scripts, release_slate all pass locally.
- Journal entry written; PLAN.md Task 2.3 ticked. No release note (CI-only).
- Rationale comments moved from qa.yml to the action header.
