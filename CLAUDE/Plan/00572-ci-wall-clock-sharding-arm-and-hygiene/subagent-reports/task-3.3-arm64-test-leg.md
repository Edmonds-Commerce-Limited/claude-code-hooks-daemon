# Task 3.3: non-blocking arm64 test leg

## Arch-aware tests

Hard-coded x86_64 real-binary paths replaced by the product's mapping
(`utils/relay_host.host_relay_target`):

- `tests/relay_gate_guard.py`: new `host_relay_build_path()`; `_RELAY_BUILD` uses it.
  An unsupported host gets a path that never exists (tests skip).
- `tests/integration/test_relay_guard_fail_open.py`, `test_relay_mid_exchange_timeout_fails_open.py`:
  `_RELAY_BINARY = host_relay_build_path()`.
- `tests/unit/screen/test_hooks_screen_binary.py`: `TARGET` from `host_relay_target()`
  (x86_64 fallback for unsupported hosts), `BINARY` and the cold-build `--target` use it.
- New unit tests in `tests/unit/test_relay_build_staleness.py` cover the helper for both
  architectures and an unsupported host.

Left alone on purpose: tmp-file names in `test_transport_probe.py` and
`test_relay_build_staleness.py` (fake files, no real binary), and tests that pass an
explicit `machine=` argument.

## qa.yml `arm64-tests`

`ubuntu-24.04-arm`, job-level `continue-on-error: true`, `needs: classify`, skipped on the
docs tier, 90 min timeout. Steps: checkout, shared `setup-env` action, native relay build
(`RELAY_TARGET=aarch64-unknown-linux-musl`, installed to `untracked/bin/hooks-relay`), the
six unit shards via `run_test_matrix.py`, artefact upload on failure. Not in `qa-gate`
`needs`. All `uses:` reuse the SHAs already in qa.yml.

`test-shards.yml` was not reused: it hard-codes `ubuntu-latest` and an x86_64 relay build, so
a runner input would have touched every caller. `relay/build.sh` still defaults to x86_64.

## Tests

`tests/integration/test_ci_arm64_tests.py` pins runner, `continue-on-error`, absence from the
gate's needs, tier skip, shared setup action, aarch64-only relay build, unit shards, timeout.
`test_ci_setup_env_action.py` setup-env user count 9 to 10.
