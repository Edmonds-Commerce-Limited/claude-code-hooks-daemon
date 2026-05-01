# Single-Python 3.9 fixture for v3.9.1 field-regression test (Plan 00103 Phase 5).
#
# Reproduces a bootstrap-fail environment: only Python 3.9 is available, no
# versioned `python3.NN >= 3.11` interpreter exists. The bootstrap entry
# points (`install.sh`, `upgrade.sh`) MUST exit non-zero with a clear
# directive — falling back to the diceroll `python3` would be a silent
# regression of the v3.9.1 fix.
#
# Used by tests/acceptance/test_v391_field_regression.py.
#
# Build:    podman build -t hooks-daemon-py39 -f single-python-39.Dockerfile .
# Run:      podman run --rm hooks-daemon-py39 bash scripts/install.sh
#           (expected: exit non-zero, stderr names 3.11 minimum)

FROM python:3.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
