# N281: secret_file_guard verdict differs between 12,500 and 100,000 characters

## Cause

Not a fail-open. In the CI message (`large vs small`) the LARGE input was the
one denied: `(True, 'deny', False)` at 100,000 against `(False, None, False)` at
12,500. `SecretFileGuardHandler._matched_pattern_and_route` converts the
`TimeoutError` the scan raises past `sfm.SCAN_DEADLINE_SECONDS` (5s) into a deny
("could not be verified"). So a slow runner makes the larger input denied, which
is the safe direction.

Evidence (3.11 venv, development host):

- `wildcards` at 12,500: 0.204s, allowed. At 100,000: 1.709s, allowed. Linear.
- With `time.monotonic` forced to advance 1s per read, both sizes return the same
  could-not-finish deny route.
- A runner about 3x slower puts the 100,000 case past 5s and leaves 12,500 under
  it, giving exactly the reported divergence on 3.11/3.12.

## Fix

Test-only, in `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py`:

- autouse `_host_independent_scan_deadline` sets the deadline to 120s for the
  sweep (precedent: `_HOST_INDEPENDENT_DEADLINE_SECONDS` in
  `test_secret_file_guard.py`, N101/N265). Growth is still checked by the ratio.
- `TestSweepVerdictIsHostIndependent`: asserts the sweep deadline, and pins that
  an expired deadline denies a wildcard command at both sizes with the
  could-not-finish reason. The first test was red before the fixture; the two
  fail-closed pins were green from the start (no source defect to fix).

No source change, so no release note. N281 ledger entry updated.

## Not verified

- The CI slow-runner timing itself (inferred from the 1.7s local figure and the
  forced-clock reproduction, not observed on a 3.11/3.12 runner).
- Pyright reports only `Import "pytest" could not be resolved` (environment, the
  venv path given is not resolved by pyright); mypy, ruff, black clean.
