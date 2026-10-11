# py3.13 venv resolver failures (sonnet)

Root cause: TEST bug, not a product bug, and unrelated to Plan 00500 Task 3.1 (the probe watchdog).

- Both tests built the "matching" venv from `python_venv_fingerprint()` (no root), giving `venv-py313-ea2cfcd1`. The resolver (`paths.py resolve-venv`) keys on `python_venv_fingerprint(daemon_dir)`, which is slug-prefixed (`venv-<slug>-py313-...`). The slug-less name is therefore never an exact keyed hit; it is only found by the sorted `untracked.glob("venv-*")` scan fallback.
- The foreign venv is hardcoded `venv-py313-deadbeef`. Sorted scan picks the first eligible name. Under 3.13 the matching name is `venv-py313-ea2cfcd1`, and `deadbeef` < `ea2cfcd1`, so the foreign one wins. Under 3.11 the matching name starts `venv-py311-`, and `py311` < `py313`, so the test passed by sort luck, not because it exercised preference.
- Evidence: failure diff `.../venv-py313-ea2cfcd1` (expected) vs `.../venv-py313-deadbeef` (got); the watchdog/probe path is not involved (the first runnable venv is only used to run paths.py).

Fix: both tests now use `python_venv_fingerprint(daemon_dir)`, so the matching venv exercises the real keyed step (step 2) and wins regardless of sort order or interpreter version. This does not hide a product bug: the product's keyed-preference behaviour is what the tests now genuinely pin; the scan-order behaviour for slug-less legacy names is unchanged and intended.

Files: tests/integration/test_install_venv_resolver.py, tests/integration/test_skill_scripts_venv_resolution.py. No release note (no product change).
Verification: both test modules, 26 passed on py3.13 and 26 passed on py3.11.
