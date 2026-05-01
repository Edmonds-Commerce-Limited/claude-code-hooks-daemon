# Multi-Python fixture for v3.9.1 field-regression test (Plan 00103 Phase 5).
#
# Reproduces the exact field-bug environment:
#   - `python3` on PATH resolves to Python 3.9 (the broken default)
#   - `python3.13` exists as a versioned command (the working interpreter)
#
# Used by tests/acceptance/test_v391_field_regression.py to verify that
# diagnostic helper scripts (health-check.sh, daemon-cli.sh status, etc.)
# succeed via the venv when invoked with a 3.9 default `python3` on PATH.
#
# Build:    podman build -t hooks-daemon-multipy -f multi-python.Dockerfile .
# Run:      podman run --rm hooks-daemon-multipy <command>

FROM python:3.9-slim

# Install uv to manage the additional Python 3.13 alongside the apt python3 -> 3.9.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Install Python 3.13 via uv, then expose it as a versioned command on PATH.
# After this step:
#   `python3 --version`     -> Python 3.9.x
#   `python3.13 --version`  -> Python 3.13.x
RUN uv python install 3.13 \
    && ln -sf "$(uv python find 3.13)" /usr/local/bin/python3.13

WORKDIR /workspace
